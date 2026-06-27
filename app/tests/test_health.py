"""Tests for HealthChecker — one test per alert type."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import timeutils

from alerts.health import Alert, HealthChecker

UTC = timezone.utc
NOW = timeutils.now()

BASE_CONFIG = {
    "cats": {
        "pirata": {"seed_weight_kg": 6.6},
        "robin": {"seed_weight_kg": 4.4},
    },
    "health": {
        "confidence_interval_sigma": 2.0,
        "confidence_interval_window_days": 30,
        "trend_days": 3,
        "absence_hours": 24,
        "frequency_window_hours": 6,
        "frequency_max_visits": 3,
    },
}


def make_history(weights: list[float], hours_ago_start: int = 200) -> list[dict]:
    """Build a history list with evenly spaced timestamps, oldest first."""
    n = len(weights)
    return [
        {
            "timestamp": NOW - timedelta(hours=hours_ago_start - i * 24),
            "cat": "pirata",
            "weight_kg": w,
        }
        for i, w in enumerate(weights)
    ]


def make_checker(history_for_cat: list[dict]) -> HealthChecker:
    store = MagicMock()
    store.load_history_for_cat.return_value = history_for_cat
    return HealthChecker(BASE_CONFIG, store)


class TestWeightInterval:
    def test_outlier_above_triggers_warning(self):
        # 9 stable visits at 6.5, one extreme outlier
        history = make_history([6.5] * 9 + [9.5])
        checker = make_checker(history)
        alerts = checker._check_weight_interval("pirata", history)
        assert len(alerts) == 1
        assert alerts[0].severity == "warning"
        assert "encima" in alerts[0].message

    def test_outlier_below_triggers_warning(self):
        history = make_history([6.5] * 9 + [3.0])
        checker = make_checker(history)
        alerts = checker._check_weight_interval("pirata", history)
        assert len(alerts) == 1
        assert "debajo" in alerts[0].message

    def test_normal_weight_no_alert(self):
        history = make_history([6.5, 6.6, 6.4, 6.5, 6.6, 6.5, 6.7])
        checker = make_checker(history)
        assert checker._check_weight_interval("pirata", history) == []

    def test_less_than_5_samples_skipped(self):
        history = make_history([6.5, 6.5, 9.9])  # too few samples
        checker = make_checker(history)
        assert checker._check_weight_interval("pirata", history) == []


class TestTrend:
    def test_upward_trend_triggers_warning(self):
        history = make_history([6.0, 6.5, 7.0])  # 3 consecutive gains
        checker = make_checker(history)
        alerts = checker._check_trend("pirata", history)
        assert len(alerts) == 1
        assert "ganando" in alerts[0].message

    def test_downward_trend_triggers_warning(self):
        history = make_history([7.0, 6.5, 6.0])
        checker = make_checker(history)
        alerts = checker._check_trend("pirata", history)
        assert len(alerts) == 1
        assert "perdiendo" in alerts[0].message

    def test_flat_weight_no_alert(self):
        history = make_history([6.5, 6.5, 6.5])
        checker = make_checker(history)
        assert checker._check_trend("pirata", history) == []

    def test_non_monotone_no_alert(self):
        history = make_history([6.0, 6.8, 6.3])
        checker = make_checker(history)
        assert checker._check_trend("pirata", history) == []


class TestAbsence:
    def test_long_absence_triggers_critical(self):
        old_visit = [{"timestamp": NOW - timedelta(hours=30), "cat": "pirata", "weight_kg": 6.5}]
        checker = make_checker(old_visit)
        alerts = checker._check_absence("pirata", old_visit)
        assert len(alerts) == 1
        assert alerts[0].severity == "critical"

    def test_recent_visit_no_alert(self):
        recent_visit = [{"timestamp": NOW - timedelta(hours=5), "cat": "pirata", "weight_kg": 6.5}]
        checker = make_checker(recent_visit)
        assert checker._check_absence("pirata", recent_visit) == []

    def test_empty_history_no_alert(self):
        checker = make_checker([])
        assert checker._check_absence("pirata", []) == []


class TestFrequency:
    def _make_recent_visits(self, n: int) -> list[dict]:
        return [
            {"timestamp": NOW - timedelta(minutes=30 * i), "cat": "pirata", "weight_kg": 6.5}
            for i in range(n)
        ]

    def test_spike_triggers_warning(self):
        history = self._make_recent_visits(5)  # 5 > max_visits=3
        checker = make_checker(history)
        alerts = checker._check_frequency("pirata", history)
        assert len(alerts) == 1
        assert "visitas" in alerts[0].message

    def test_normal_frequency_no_alert(self):
        history = self._make_recent_visits(2)  # 2 <= max_visits=3
        checker = make_checker(history)
        assert checker._check_frequency("pirata", history) == []
