"""
Idempotency guarantees for the whole system.

Re-running any data path — a single pipeline tick, a migration, or an alert
evaluation — must converge to the same state and the same side effects as
running it once, cleanly, first time. These tests lock that in.
"""
from datetime import datetime, timedelta, timezone

import pytest

import timeutils

from classifier import Classifier
from alerts.health import Alert
from storage.sqlite_store import SQLiteStore
from storage.csv_store import CsvStore

UTC = timezone.utc
NOW = timeutils.now().replace(microsecond=0)


def make_config(tmp_path):
    return {
        "cats": {
            "pirata": {"seed_weight_kg": 6.6},
            "robin": {"seed_weight_kg": 4.4},
        },
        "classifier": {"moving_average_window_days": 14, "min_confidence_kg": 0.5},
        "storage": {
            "sqlite_path": str(tmp_path / "weights.db"),
            "csv_path": str(tmp_path / "weights.csv"),
        },
    }


# ── Data writes: re-running never duplicates ──────────────────────────────────
class TestDataWritesIdempotent:
    def _visits(self):
        return [
            {"timestamp": NOW - timedelta(days=3, hours=2), "weight_kg": 6.7},
            {"timestamp": NOW - timedelta(days=2, hours=1), "weight_kg": 4.3},
            {"timestamp": NOW - timedelta(days=1), "weight_kg": 6.5},
        ]

    def test_sqlite_rerun_is_noop(self, tmp_path):
        config = make_config(tmp_path)
        clf = Classifier(config, history=[])
        classified = [clf.classify(v) for v in self._visits()]

        store = SQLiteStore(config)
        store.write(classified)
        store.write(classified)  # full re-run
        store.write(classified[:2])  # partial re-run

        assert len(store.load_history()) == 3

    def test_csv_rerun_is_noop(self, tmp_path):
        config = make_config(tmp_path)
        clf = Classifier(config, history=[])
        classified = [clf.classify(v) for v in self._visits()]

        csv_store = CsvStore(config)
        csv_store.write(classified)
        csv_store.write(classified)
        csv_store.write(classified[:1])

        path = tmp_path / "weights.csv"
        data_rows = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                     if ln and not ln.startswith("#") and not ln.startswith("timestamp")]
        assert len(data_rows) == 3  # 3 unique rows, no duplicates across re-runs


# ── Migration: any split / resume converges to one clean run ──────────────────
class TestMigrationIdempotent:
    def _historical_visits(self):
        # Old data (>14d) — the classifier window is empty, so the threshold is the
        # fixed seed midpoint and classification is independent of batch composition.
        base = NOW - timedelta(days=200)
        return [
            {"timestamp": base + timedelta(hours=i * 7), "weight_kg": w}
            for i, w in enumerate([6.7, 4.3, 6.5, 4.4, 6.9, 4.2, 6.6, 4.5])
        ]

    def _migrate_batch(self, config, visits):
        clf = Classifier(config, history=[])
        classified = [clf.classify(v) for v in visits]
        SQLiteStore(config).write(classified)
        CsvStore(config).write(classified)

    def _dump(self, config):
        rows = SQLiteStore(config)._query(cutoff_days=10_000)
        return sorted((r["timestamp"], r["cat"], r["weight_kg"]) for r in rows)

    def test_full_run_equals_split_run(self, tmp_path):
        visits = self._historical_visits()

        clean = make_config(tmp_path / "clean")
        (tmp_path / "clean").mkdir()
        self._migrate_batch(clean, visits)

        split = make_config(tmp_path / "split")
        (tmp_path / "split").mkdir()
        # Simulate a crash after the first 5 visits, then a resume with all of them.
        self._migrate_batch(split, visits[:5])
        self._migrate_batch(split, visits)  # re-run sees everything again

        assert self._dump(clean) == self._dump(split)

    def test_rerun_does_not_grow_db(self, tmp_path):
        config = make_config(tmp_path)
        visits = self._historical_visits()
        self._migrate_batch(config, visits)
        first = self._dump(config)
        self._migrate_batch(config, visits)  # run it again
        assert self._dump(config) == first


# ── Alerts: an ongoing condition emails once, not every hour ──────────────────
class TestAlertDedup:
    def test_fingerprint_is_stable_across_message_changes(self):
        a1 = Alert(cat="robin", severity="critical", kind="absence",
                   message="Robin lleva 26.0h sin usar la caja (umbral=24h)")
        a2 = Alert(cat="robin", severity="critical", kind="absence",
                   message="Robin lleva 31.5h sin usar la caja (umbral=24h)")
        assert a1.fingerprint() == a2.fingerprint()

    def test_different_kinds_are_distinct(self):
        a = Alert(cat="pirata", severity="warning", kind="weight_interval", message="x")
        b = Alert(cat="pirata", severity="warning", kind="trend", message="y")
        assert a.fingerprint() != b.fingerprint()

    def test_recorded_fingerprint_is_suppressed_within_cooldown(self, tmp_path):
        store = SQLiteStore(make_config(tmp_path))
        store.record_sent_alerts(["robin:absence", "pirata:weight_interval"])
        recent = store.recent_alert_fingerprints(cooldown_hours=24)
        assert recent == {"robin:absence", "pirata:weight_interval"}

    def test_nothing_recorded_means_nothing_suppressed(self, tmp_path):
        store = SQLiteStore(make_config(tmp_path))
        assert store.recent_alert_fingerprints(cooldown_hours=24) == set()

    def test_dedup_filter_drops_already_sent(self, tmp_path):
        store = SQLiteStore(make_config(tmp_path))
        alerts = [
            Alert(cat="robin", severity="critical", kind="absence", message="m1"),
            Alert(cat="pirata", severity="warning", kind="trend", message="m2"),
        ]
        store.record_sent_alerts([alerts[0].fingerprint()])

        already = store.recent_alert_fingerprints(24)
        fresh = [a for a in alerts if a.fingerprint() not in already]

        assert len(fresh) == 1
        assert fresh[0].cat == "pirata"

    def test_record_is_idempotent_for_filtering(self, tmp_path):
        # Recording the same fingerprint twice still suppresses exactly that alert.
        store = SQLiteStore(make_config(tmp_path))
        store.record_sent_alerts(["robin:absence"])
        store.record_sent_alerts(["robin:absence"])
        assert store.recent_alert_fingerprints(24) == {"robin:absence"}
