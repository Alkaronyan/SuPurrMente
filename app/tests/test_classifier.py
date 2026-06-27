"""Tests for the moving-average classifier."""
from datetime import datetime, timedelta, timezone

import pytest

import timeutils

from classifier import Classifier, ClassifiedVisit

BASE_CONFIG = {
    "cats": {
        "pirata": {"seed_weight_kg": 6.6},
        "robin": {"seed_weight_kg": 4.4},
    },
    "classifier": {
        "moving_average_window_days": 14,
        "min_confidence_kg": 0.5,
    },
}

NOW = timeutils.now()


def make_visit(weight_kg: float, offset_hours: int = 0) -> dict:
    return {
        "timestamp": NOW - timedelta(hours=offset_hours),
        "weight_kg": weight_kg,
    }


class TestSeedClassification:
    """With no history, seed weights define the threshold (5.5 kg)."""

    def setup_method(self):
        self.clf = Classifier(BASE_CONFIG, history=[])

    def test_heavy_weight_classified_as_pirata(self):
        result = self.clf.classify(make_visit(6.5))
        assert result.cat == "pirata"

    def test_light_weight_classified_as_robin(self):
        result = self.clf.classify(make_visit(4.3))
        assert result.cat == "robin"

    def test_returns_classified_visit_dataclass(self):
        result = self.clf.classify(make_visit(6.5))
        assert isinstance(result, ClassifiedVisit)
        assert result.weight_kg == pytest.approx(6.5)

    def test_confidence_is_distance_from_threshold(self):
        result = self.clf.classify(make_visit(6.5))
        # threshold = 5.5, weight = 6.5 → confidence = 1.0
        assert result.confidence == pytest.approx(1.0)

    def test_raw_weight_preserved(self):
        result = self.clf.classify(make_visit(6.5))
        assert result.raw_weight_kg == pytest.approx(result.weight_kg)


class TestThresholdAdapts:
    """After several classified visits, moving averages update."""

    def test_moving_average_shifts_threshold(self):
        clf = Classifier(BASE_CONFIG, history=[])
        # Classify 5 pirata visits at 7.0 kg
        for i in range(5):
            clf.classify(make_visit(7.0, offset_hours=i + 10))
        # Threshold should now be closer to (7.0 + 4.4) / 2 = 5.7
        result = clf.classify(make_visit(6.0))
        # 6.0 is above the updated threshold, should still be pirata
        assert result.cat == "pirata"

    def test_seeded_history_used(self):
        history = [
            {"timestamp": NOW - timedelta(days=i), "cat": "pirata", "weight_kg": 7.0}
            for i in range(10)
        ]
        clf = Classifier(BASE_CONFIG, history=history)
        # Pirata average should be ~7.0, threshold ~5.7
        result = clf.classify(make_visit(6.0))
        assert result.cat == "pirata"


class TestClassifyKnown:
    """Live-API path: cat comes from Whisker, classifier only validates."""

    def make_known(self, cat: str, weight_kg: float) -> dict:
        return {"timestamp": NOW, "cat": cat, "weight_kg": weight_kg}

    def test_trusts_api_cat_even_against_threshold(self):
        clf = Classifier(BASE_CONFIG, history=[])
        # A light weight labelled pirata by the API is still stored as pirata.
        result = clf.classify_known(self.make_known("pirata", 4.0))
        assert result.cat == "pirata"

    def test_normal_reading_kept(self):
        clf = Classifier(BASE_CONFIG, history=[])
        result = clf.classify_known(self.make_known("robin", 4.3))
        assert result.cat == "robin"
        assert isinstance(result, ClassifiedVisit)
        assert result.raw_weight_kg == pytest.approx(4.3)

    def test_updates_moving_average_with_known_cat(self):
        clf = Classifier(BASE_CONFIG, history=[])
        for i in range(5):
            clf.classify_known({"timestamp": NOW - timedelta(hours=i + 10),
                                "cat": "pirata", "weight_kg": 7.0})
        assert clf._averages["pirata"] == pytest.approx(7.0)


class TestEdgeCases:
    def test_cats_sorted_heaviest_first(self):
        clf = Classifier(BASE_CONFIG, history=[])
        # pirata (6.6) should be cats[0]
        assert clf._cats[0] == "pirata"
        assert clf._cats[1] == "robin"
