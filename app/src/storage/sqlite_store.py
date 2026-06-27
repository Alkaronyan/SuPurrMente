import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import timeutils

log = logging.getLogger(__name__)

DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS visits (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL UNIQUE,
    cat           TEXT NOT NULL,
    weight_kg     REAL NOT NULL,
    raw_weight_kg REAL NOT NULL,
    confidence    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cat_ts ON visits (cat, timestamp);

CREATE TABLE IF NOT EXISTS sent_alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    sent_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sent_at ON sent_alerts (sent_at);

-- One row per *change* in device/library versions, so we keep a history of which
-- firmware + pylitterbot we ran against (the unofficial API has changed before).
CREATE TABLE IF NOT EXISTS api_meta (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at      TEXT NOT NULL,
    firmware        TEXT,
    library_version TEXT,
    model           TEXT,
    serial          TEXT
);

-- Daily total clean-cycle count (robot-level, both cats). Keyed by local day so a
-- day's count is replaced as it grows through the day.
CREATE TABLE IF NOT EXISTS box_usage (
    day    TEXT PRIMARY KEY,   -- 'YYYY-MM-DD' local
    cycles INTEGER NOT NULL
);

-- One snapshot of robot state per fetch cycle: litter/drawer levels, online status.
CREATE TABLE IF NOT EXISTS robot_snapshots (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at         TEXT NOT NULL,
    litter_level       REAL,
    waste_drawer_level REAL,
    is_online          INTEGER,
    last_seen          TEXT
);
"""

_META_FIELDS = ("firmware", "library_version", "model", "serial")


class SQLiteStore:
    def __init__(self, config: dict) -> None:
        self._path = Path(config["storage"]["sqlite_path"])
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def write(self, visits: list) -> None:
        rows = [
            (v.timestamp.strftime(DATE_FORMAT), v.cat, v.weight_kg, v.raw_weight_kg, v.confidence)
            for v in visits
        ]
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO visits (timestamp, cat, weight_kg, raw_weight_kg, confidence) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
        log.info("Wrote %d visit(s) to SQLite (duplicates skipped)", len(rows))

    def recent_alert_fingerprints(self, cooldown_hours: float) -> set[str]:
        """Fingerprints of alerts already sent within the cooldown window.

        Used to suppress re-sending the same ongoing alert on every hourly run.
        """
        cutoff = (timeutils.now() - timedelta(hours=cooldown_hours)).strftime(DATE_FORMAT)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT fingerprint FROM sent_alerts WHERE sent_at >= ?",
                (cutoff,),
            ).fetchall()
        return {r[0] for r in rows}

    def record_sent_alerts(self, fingerprints: list[str]) -> None:
        """Persist that these alert fingerprints were just sent."""
        if not fingerprints:
            return
        now = timeutils.now().strftime(DATE_FORMAT)
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO sent_alerts (fingerprint, sent_at) VALUES (?, ?)",
                [(fp, now) for fp in fingerprints],
            )

    def record_api_meta(self, firmware, library_version, model, serial) -> Optional[dict]:
        """Persist device/library versions, but only insert a new row when something
        changed vs the last record. Returns {'field','old','new'} for the first
        changed field (to drive an alert), or None on first record / no change.
        """
        new = {"firmware": firmware, "library_version": library_version,
               "model": model, "serial": serial}
        with self._connect() as conn:
            row = conn.execute(
                "SELECT firmware, library_version, model, serial "
                "FROM api_meta ORDER BY id DESC LIMIT 1"
            ).fetchone()

            change = None
            if row is not None:
                for f in _META_FIELDS:
                    if (row[f] or None) != (new[f] or None):
                        change = {"field": f, "old": row[f], "new": new[f]}
                        break

            if row is None or change is not None:
                now = timeutils.now().strftime(DATE_FORMAT)
                conn.execute(
                    "INSERT INTO api_meta (checked_at, firmware, library_version, model, serial) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (now, firmware, library_version, model, serial),
                )
        return change  # None on first-ever record (baseline, not an alert)

    def upsert_box_usage(self, cycle_history: list) -> None:
        """Store daily clean-cycle counts. cycle_history is [(date, cycles)].

        REPLACE by day so today's partial count is refreshed each fetch.
        """
        rows = [(d.isoformat() if hasattr(d, "isoformat") else str(d), int(c))
                for d, c in cycle_history]
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO box_usage (day, cycles) VALUES (?, ?) "
                "ON CONFLICT(day) DO UPDATE SET cycles = excluded.cycles",
                rows,
            )

    def record_robot_snapshot(self, litter_level, waste_drawer_level, is_online, last_seen) -> None:
        """Append a robot-state snapshot for this fetch cycle."""
        now = timeutils.now().strftime(DATE_FORMAT)
        ls = last_seen.strftime(DATE_FORMAT) if last_seen is not None else None
        online = None if is_online is None else int(bool(is_online))
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO robot_snapshots "
                "(checked_at, litter_level, waste_drawer_level, is_online, last_seen) "
                "VALUES (?, ?, ?, ?, ?)",
                (now, litter_level, waste_drawer_level, online, ls),
            )

    def existing_timestamps_by_cat(self) -> dict:
        """{cat: sorted[datetime]} of all stored visits — for fuzzy migration dedup."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT cat, timestamp FROM visits ORDER BY cat, timestamp"
            ).fetchall()
        out: dict = {}
        for r in rows:
            out.setdefault(r["cat"], []).append(
                datetime.strptime(r["timestamp"], DATE_FORMAT).replace(tzinfo=timeutils.LOCAL_TZ)
            )
        return out

    def last_timestamp(self) -> Optional[datetime]:
        """Most recent stored timestamp — used to skip already-seen API records."""
        with self._connect() as conn:
            row = conn.execute("SELECT MAX(timestamp) FROM visits").fetchone()
        if not row or row[0] is None:
            return None
        return datetime.strptime(row[0], DATE_FORMAT).replace(tzinfo=timeutils.LOCAL_TZ)

    def load_history(self) -> list[dict]:
        """Last 30 days of visits for seeding the classifier's moving averages."""
        return self._query(cutoff_days=30)

    def load_history_for_cat(self, cat: str, days: int = 30) -> list[dict]:
        """Per-cat history for health checks."""
        cutoff = self._cutoff(days)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT timestamp, cat, weight_kg FROM visits "
                "WHERE cat = ? AND timestamp >= ? ORDER BY timestamp",
                (cat, cutoff),
            ).fetchall()
        return self._to_dicts(rows)

    def _query(self, cutoff_days: int) -> list[dict]:
        cutoff = self._cutoff(cutoff_days)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT timestamp, cat, weight_kg FROM visits "
                "WHERE timestamp >= ? ORDER BY timestamp",
                (cutoff,),
            ).fetchall()
        return self._to_dicts(rows)

    @staticmethod
    def _cutoff(days: int) -> str:
        return (timeutils.now() - timedelta(days=days)).strftime(DATE_FORMAT)

    @staticmethod
    def _to_dicts(rows) -> list[dict]:
        return [
            {
                "timestamp": datetime.strptime(r["timestamp"], DATE_FORMAT).replace(tzinfo=timeutils.LOCAL_TZ),
                "cat": r["cat"],
                "weight_kg": r["weight_kg"],
            }
            for r in rows
        ]
