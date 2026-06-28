"""
One-time migration script. Run before the first cron execution:

    docker compose run --rm tracker python src/migrate.py

Reads all CSV files from deprecated/, classifies records using seed weights,
ingests into SQLite, appends to the main CSV, then moves each file to
deprecated/done/ when complete.

Handles all three timestamp formats exported by the Whisker app:
  Format A (Jan–Apr 2025): M/DD H:MMAM  / M/DD H:MMPM   (English 12h)
  Format B (Jun 2025):     M/DD H:MMa. m. / M/DD H:MMp. m.  (Spanish 12h)
  Format C (Jul 2025+):    DD/M HH:MM  / DD/MM HH:MM    (European 24h)
"""
import bisect
import csv
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

import timeutils
from classifier import Classifier
from storage.sqlite_store import SQLiteStore
from storage.csv_store import CsvStore

log = logging.getLogger(__name__)

ACTIVITY_WEIGHT = "Peso de la mascota registrado"


def load_config() -> dict:
    for path in [Path("/app/config.yml"), Path("config.yml")]:
        if path.exists():
            with open(path) as f:
                return yaml.safe_load(f)
    raise FileNotFoundError("config.yml not found")


def extract_year(filename: str) -> int:
    match = re.search(r"20\d{2}", filename)
    if not match:
        raise ValueError(f"Cannot extract year from filename: {filename}")
    return int(match.group())


def _normalize_spaces(s: str) -> str:
    """The Whisker Spanish export separates 'a.'/'p.' from 'm.' with a non-breaking
    space (\\xa0) or narrow no-break space (\\u202f), not a regular space. Normalise
    them so 'p.\\xa0m.' is recognised as format B instead of silently falling through.
    """
    return re.sub("[    ]", " ", s)


def detect_format(timestamp_str: str) -> str:
    ts = _normalize_spaces(timestamp_str)
    if "AM" in ts or "PM" in ts:
        return "A"
    if "a. m." in ts or "p. m." in ts:
        return "B"
    return "C"


def parse_timestamp(ts: str, fmt: str, year: int) -> datetime:
    ts = _normalize_spaces(ts).strip()
    # Newer Spanish export (Jun 2026+) inserts ", a las " between date and time, e.g.
    # "26/6, a las 8:16". Strip it so the European 24h branch (%d/%m %H:%M) accepts it.
    ts = re.sub(r",?\s*a\s+las\s+", " ", ts).strip()
    if fmt == "A":
        dt = datetime.strptime(ts, "%m/%d %I:%M%p")
    elif fmt == "B":
        ts_norm = ts.replace("a. m.", "AM").replace("p. m.", "PM")
        dt = datetime.strptime(ts_norm, "%m/%d %I:%M%p")
    else:
        dt = datetime.strptime(ts, "%d/%m %H:%M")
    # CSV exports are already in local Madrid wall-clock — tag as such, don't shift.
    return dt.replace(year=year, tzinfo=timeutils.LOCAL_TZ)


def parse_weight(value_str: str) -> float:
    return float(value_str.replace(",", ".").replace("kg", "").strip())


def _has_near(sorted_ts: list, ts: datetime, tol_seconds: float) -> bool:
    """True if `sorted_ts` (ascending) has any value within ±tol_seconds of `ts`.

    Used to skip CSV rows that overlap live-API visits of the same cat: the two
    sources timestamp the same physical event seconds apart (API has seconds, the
    CSV export only minutes), so exact-timestamp dedup misses them.
    """
    if not sorted_ts:
        return False
    i = bisect.bisect_left(sorted_ts, ts)
    for j in (i - 1, i):
        if 0 <= j < len(sorted_ts) and abs((sorted_ts[j] - ts).total_seconds()) <= tol_seconds:
            return True
    return False


def parse_file(path: Path) -> tuple[list[dict], int]:
    """Return (visits, skipped) where skipped counts weight rows that failed to parse.

    A high skip count signals a format the parser does not yet handle — the caller
    uses it to refuse archiving the file rather than losing data silently.
    """
    year = extract_year(path.name)
    visits = []
    skipped = 0
    fmt = None

    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            activity = row.get("Actividad", "").strip()
            if not activity.startswith(ACTIVITY_WEIGHT):
                continue
            value = row.get("Valor", "").strip()
            if not value or value == "-":
                continue
            ts_raw = row.get("Marca de tiempo", "").strip()
            if not ts_raw:
                continue
            if fmt is None:
                fmt = detect_format(ts_raw)
            try:
                timestamp = parse_timestamp(ts_raw, fmt, year)
                weight_kg = parse_weight(value)
            except (ValueError, KeyError) as e:
                log.warning("Skipping unparseable row in %s: %s — %s", path.name, row, e)
                skipped += 1
                continue
            visits.append({"timestamp": timestamp, "weight_kg": weight_kg})

    return visits, skipped


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()

    deprecated = Path("deprecated")
    if not deprecated.is_dir():
        log.info("No existe deprecated/ — nada que migrar (datos vienen de la API / restore)")
        return

    csv_files = sorted(deprecated.glob("*.csv"))
    if not csv_files:
        log.info("No CSV files found in deprecated/ — nothing to migrate")
        return

    done = deprecated / "done"
    done.mkdir(parents=True, exist_ok=True)

    # A file is only archived if it parsed cleanly. If more than this fraction of its
    # weight rows fail, we treat it as failed (likely an unhandled format) and leave it
    # in deprecated/ so a fixed re-run can pick it up — never lose data silently.
    max_skip_rate = config.get("migration", {}).get("max_skip_rate", 0.05)

    all_visits = []
    failed_files = []

    for path in csv_files:
        log.info("Parsing %s ...", path.name)
        try:
            visits, skipped = parse_file(path)
        except Exception:
            log.exception("Failed to parse %s", path.name)
            failed_files.append(path)
            continue

        total = len(visits) + skipped
        skip_rate = (skipped / total) if total else 0.0
        log.info("  → %d weight event(s) found, %d skipped", len(visits), skipped)

        if skip_rate > max_skip_rate:
            log.error(
                "  ✗ %s: %d/%d rows (%.0f%%) failed to parse — NOT archiving so no data "
                "is lost. Fix the parser and re-run.",
                path.name, skipped, total, skip_rate * 100,
            )
            failed_files.append(path)
            # Still ingest what parsed (idempotent), but keep the file for a clean re-run.
        all_visits.extend(visits)

    if not all_visits:
        log.warning("No weight events found across all files")
        return

    all_visits.sort(key=lambda v: v["timestamp"])
    log.info(
        "Total: %d event(s) across %d file(s), spanning %s → %s",
        len(all_visits),
        len(csv_files),
        all_visits[0]["timestamp"].date(),
        all_visits[-1]["timestamp"].date(),
    )

    store = SQLiteStore(config)
    csv_store = CsvStore(config)
    classifier = Classifier(config, history=[])

    classified = [classifier.classify(v) for v in all_visits]

    pirata_count = sum(1 for v in classified if v.cat == "pirata")
    robin_count = sum(1 for v in classified if v.cat == "robin")
    log.info("Clasificación: pirata=%d, robin=%d", pirata_count, robin_count)

    # Fuzzy dedup vs whatever is already stored (e.g. live-API rows for the same
    # week): drop CSV rows that land within tolerance of an existing same-cat visit.
    tol = config.get("migration", {}).get("dedup_tolerance_seconds", 120)
    existing = store.existing_timestamps_by_cat()
    kept = [v for v in classified
            if not _has_near(existing.get(v.cat, []), v.timestamp, tol)]
    dropped = len(classified) - len(kept)
    if dropped:
        log.info("Dedup: %d fila(s) CSV omitidas (a ±%ds de una visita ya almacenada)", dropped, tol)

    store.write(kept)
    csv_store.write(kept)

    parseable = [p for p in csv_files if p not in failed_files]
    for path in parseable:
        # .replace() (not .rename()) so a re-run never crashes on Windows when
        # done/<name> already exists. The data is already deduped in SQLite/CSV
        # by timestamp, so overwriting the archived copy is safe and idempotent.
        path.replace(done / path.name)

    if failed_files:
        log.warning(
            "%d archivo(s) fallaron y NO se movieron: %s",
            len(failed_files),
            [p.name for p in failed_files],
        )

    log.info("Migración completa: %d registro(s) escritos", len(classified))


if __name__ == "__main__":
    main()
