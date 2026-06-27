import logging

import timeutils
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean, stdev

log = logging.getLogger(__name__)


@dataclass
class Alert:
    cat: str
    severity: str   # "warning" | "critical"
    message: str
    kind: str = ""  # weight_interval | trend | absence | frequency — stable id for dedup

    def fingerprint(self) -> str:
        """Stable identity for dedup: same cat + same kind = same alert.

        Intentionally excludes the message (which carries varying numbers) so the
        same ongoing condition is recognised across hourly runs.
        """
        return f"{self.cat}:{self.kind}"


class HealthChecker:
    def __init__(self, config: dict, store) -> None:
        self._cfg = config["health"]
        self._store = store
        self._cats = list(config["cats"].keys())

    def check_all(self) -> list[Alert]:
        alerts = []
        for cat in self._cats:
            history = self._store.load_history_for_cat(
                cat, days=self._cfg["confidence_interval_window_days"]
            )
            if not history:
                continue
            alerts.extend(self._check_weight_interval(cat, history))
            alerts.extend(self._check_trend(cat, history))
            alerts.extend(self._check_absence(cat, history))
            alerts.extend(self._check_frequency(cat, history))
        return alerts

    def _check_weight_interval(self, cat: str, history: list[dict]) -> list[Alert]:
        weights = [r["weight_kg"] for r in history if r["weight_kg"] is not None]
        if len(weights) < 5:
            return []
        sigma = self._cfg["confidence_interval_sigma"]
        mu = mean(weights)
        sd = stdev(weights)
        latest = weights[-1]
        if abs(latest - mu) > sigma * sd:
            direction = "por encima de" if latest > mu else "por debajo de"
            return [Alert(
                cat=cat,
                severity="warning",
                kind="weight_interval",
                message=(
                    f"{cat.title()} pesa {latest:.2f} kg, {direction} {sigma}σ "
                    f"(media={mu:.2f} kg, σ={sd:.2f} kg)"
                ),
            )]
        return []

    def _check_trend(self, cat: str, history: list[dict]) -> list[Alert]:
        n = self._cfg["trend_days"]
        weights = [r["weight_kg"] for r in history if r["weight_kg"] is not None]
        if len(weights) < n:
            return []
        recent = weights[-n:]
        if all(recent[i] < recent[i + 1] for i in range(n - 1)):
            return [Alert(cat=cat, severity="warning", kind="trend",
                          message=f"{cat.title()} lleva {n} días consecutivos ganando peso")]
        if all(recent[i] > recent[i + 1] for i in range(n - 1)):
            return [Alert(cat=cat, severity="warning", kind="trend",
                          message=f"{cat.title()} lleva {n} días consecutivos perdiendo peso")]
        return []

    def _check_absence(self, cat: str, history: list[dict]) -> list[Alert]:
        if not history:
            return []
        last_visit = max(r["timestamp"] for r in history)
        if last_visit.tzinfo is None:
            last_visit = last_visit.replace(tzinfo=timeutils.LOCAL_TZ)
        threshold_h = self._cfg["absence_hours"]
        elapsed_h = (timeutils.now() - last_visit).total_seconds() / 3600
        if elapsed_h > threshold_h:
            return [Alert(
                cat=cat,
                severity="critical",
                kind="absence",
                message=f"{cat.title()} lleva {elapsed_h:.1f}h sin usar la caja (umbral={threshold_h}h)",
            )]
        return []

    def _check_frequency(self, cat: str, history: list[dict]) -> list[Alert]:
        window_h = self._cfg["frequency_window_hours"]
        max_visits = self._cfg["frequency_max_visits"]
        cutoff = timeutils.now() - timedelta(hours=window_h)
        recent = [
            r for r in history
            if (r["timestamp"].replace(tzinfo=timeutils.LOCAL_TZ)
                if r["timestamp"].tzinfo is None
                else r["timestamp"]) >= cutoff
        ]
        if len(recent) > max_visits:
            return [Alert(
                cat=cat,
                severity="warning",
                kind="frequency",
                message=(
                    f"{cat.title()} tuvo {len(recent)} visitas en las últimas {window_h}h "
                    f"(máx={max_visits})"
                ),
            )]
        return []
