"""Robot-level data: box-usage storage, state snapshots, and robot alerts."""
from datetime import date
from types import SimpleNamespace

import timeutils
from alerts import robot_health
from storage.sqlite_store import SQLiteStore

CONFIG = {"robot_health": {"litter_low_pct": 10, "drawer_full_pct": 90}}


def result(**kw):
    base = dict(litter_level=None, waste_drawer_level=None, is_online=None,
                last_seen=None, cycle_history=[])
    base.update(kw)
    return SimpleNamespace(**base)


class TestRobotAlerts:
    def test_litter_low_alerts(self):
        a = robot_health.check(result(litter_level=8), CONFIG)
        assert len(a) == 1 and a[0].kind == "litter_low"

    def test_litter_ok_no_alert(self):
        assert robot_health.check(result(litter_level=80), CONFIG) == []

    def test_drawer_full_alerts(self):
        a = robot_health.check(result(waste_drawer_level=95), CONFIG)
        assert len(a) == 1 and a[0].kind == "drawer_full"

    def test_offline_is_critical(self):
        a = robot_health.check(result(is_online=False), CONFIG)
        assert len(a) == 1 and a[0].kind == "offline" and a[0].severity == "critical"

    def test_online_true_no_alert(self):
        assert robot_health.check(result(is_online=True), CONFIG) == []

    def test_none_values_are_safe(self):
        assert robot_health.check(result(), CONFIG) == []

    def test_multiple_at_once(self):
        a = robot_health.check(result(litter_level=5, waste_drawer_level=99, is_online=False), CONFIG)
        kinds = {x.kind for x in a}
        assert kinds == {"litter_low", "drawer_full", "offline"}


class TestBoxUsage:
    def _store(self, tmp_path):
        return SQLiteStore({"storage": {"sqlite_path": str(tmp_path / "u.db")}})

    def _read(self, store):
        with store._connect() as c:
            return dict(c.execute("SELECT day, cycles FROM box_usage").fetchall())

    def test_upsert_inserts(self, tmp_path):
        store = self._store(tmp_path)
        store.upsert_box_usage([(date(2026, 6, 25), 4), (date(2026, 6, 26), 5)])
        assert self._read(store) == {"2026-06-25": 4, "2026-06-26": 5}

    def test_upsert_replaces_same_day(self, tmp_path):
        store = self._store(tmp_path)
        store.upsert_box_usage([(date(2026, 6, 26), 3)])
        store.upsert_box_usage([(date(2026, 6, 26), 7)])  # day grew
        assert self._read(store) == {"2026-06-26": 7}

    def test_empty_is_noop(self, tmp_path):
        store = self._store(tmp_path)
        store.upsert_box_usage([])
        assert self._read(store) == {}


class TestRobotSnapshot:
    def _store(self, tmp_path):
        return SQLiteStore({"storage": {"sqlite_path": str(tmp_path / "s.db")}})

    def test_records_snapshot(self, tmp_path):
        store = self._store(tmp_path)
        store.record_robot_snapshot(90.0, 73.0, True, timeutils.now())
        with store._connect() as c:
            row = c.execute(
                "SELECT litter_level, waste_drawer_level, is_online FROM robot_snapshots"
            ).fetchone()
        assert row["litter_level"] == 90.0
        assert row["waste_drawer_level"] == 73.0
        assert row["is_online"] == 1

    def test_handles_nones(self, tmp_path):
        store = self._store(tmp_path)
        store.record_robot_snapshot(None, None, None, None)
        with store._connect() as c:
            n = c.execute("SELECT COUNT(*) FROM robot_snapshots").fetchone()[0]
        assert n == 1
