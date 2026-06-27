import logging

import timeutils
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class ClassifiedVisit:
    timestamp: datetime
    cat: str            # "pirata" or "robin"
    weight_kg: float
    raw_weight_kg: float
    confidence: float   # distance in kg between weight and the classification threshold


class Classifier:
    """
    Classifies each raw visit to a cat using a dynamic moving-average threshold.

    Threshold = midpoint between the two cats' moving averages, recalculated after
    each classified visit. Seed weights are used until enough history exists.
    """

    def __init__(self, config: dict, history: list[dict]) -> None:
        cats_config = config["cats"]
        self._cats = list(cats_config.keys())  # order: [heavier, lighter]
        self._cats.sort(key=lambda c: cats_config[c]["seed_weight_kg"], reverse=True)

        self._window = timedelta(days=config["classifier"]["moving_average_window_days"])
        self._min_confidence = config["classifier"]["min_confidence_kg"]

        self._averages: dict[str, float] = {
            cat: cfg["seed_weight_kg"] for cat, cfg in cats_config.items()
        }
        self._history: list[dict] = list(history)
        self._refresh_averages()

    def classify(self, visit: dict) -> ClassifiedVisit:
        weight = visit["weight_kg"]
        threshold = self._threshold()

        # Heavier cat is index 0; if weight >= threshold it's the heavier cat
        cat = self._cats[0] if weight >= threshold else self._cats[1]
        confidence = abs(weight - threshold)

        if confidence < self._min_confidence:
            log.warning(
                "Low confidence: weight=%.3f kg, threshold=%.3f kg, "
                "confidence=%.3f kg (min=%.3f) — possible misclassification",
                weight, threshold, confidence, self._min_confidence,
            )

        classified = ClassifiedVisit(
            timestamp=visit["timestamp"],
            cat=cat,
            weight_kg=weight,
            raw_weight_kg=weight,
            confidence=confidence,
        )

        self._history.append({
            "timestamp": visit["timestamp"],
            "cat": cat,
            "weight_kg": weight,
        })
        self._refresh_averages()

        return classified

    def classify_known(self, visit: dict) -> ClassifiedVisit:
        """Live-API path: the cat is already identified by Whisker.

        Trust the API's cat, but warn if the weight-based threshold disagrees — a
        cheap guard against a misread or a swapped pet. Still updates the moving
        average with the correct cat so future thresholds stay accurate.
        """
        cat = visit["cat"]
        weight = visit["weight_kg"]
        threshold = self._threshold()
        predicted = self._cats[0] if weight >= threshold else self._cats[1]
        if predicted != cat:
            log.warning(
                "API identifies %s but weight %.2f kg suggests %s (threshold=%.2f kg) "
                "— trusting API",
                cat, weight, predicted, threshold,
            )

        self._history.append({
            "timestamp": visit["timestamp"],
            "cat": cat,
            "weight_kg": weight,
        })
        self._refresh_averages()

        return ClassifiedVisit(
            timestamp=visit["timestamp"],
            cat=cat,
            weight_kg=weight,
            raw_weight_kg=weight,
            confidence=round(abs(weight - threshold), 3),
        )

    def _threshold(self) -> float:
        return (self._averages[self._cats[0]] + self._averages[self._cats[1]]) / 2

    def _refresh_averages(self) -> None:
        cutoff = timeutils.now() - self._window
        recent: dict[str, list[float]] = defaultdict(list)

        for record in self._history:
            ts = record["timestamp"]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timeutils.LOCAL_TZ)
            if ts >= cutoff:
                recent[record["cat"]].append(record["weight_kg"])

        for cat in self._cats:
            samples = recent.get(cat, [])
            if samples:
                self._averages[cat] = round(mean(samples), 3)
