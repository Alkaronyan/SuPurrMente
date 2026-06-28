"""Tests para crosscheck.check_assignments — confirma la asignación de la API contra
la tendencia reciente de cada gato."""
from datetime import timedelta

import timeutils
import crosscheck

NOW = timeutils.now()

CONFIG = {
    "cats": {"pirata": {"seed_weight_kg": 6.6}, "robin": {"seed_weight_kg": 4.4}},
    "crosscheck": {
        "enabled": True, "window_days": 10, "min_points": 3, "margin_kg": 0.3, "mad_k": 4.0,
    },
}


class FakeStore:
    def __init__(self, hist: dict) -> None:
        self._hist = hist

    def load_history_for_cat(self, cat: str, days: int) -> list:
        return self._hist.get(cat, [])


def hist(cat: str, weights: list) -> list:
    """Lecturas espaciadas 12h, todas anteriores a NOW, más antigua primero."""
    n = len(weights)
    return [
        {"timestamp": NOW - timedelta(hours=12 * (n - i)), "cat": cat, "weight_kg": w}
        for i, w in enumerate(weights)
    ]


def visit(cat: str, weight: float):
    return {"timestamp": NOW, "weight_kg": weight, "cat": cat}


PIRATA_STABLE = [6.6, 6.5, 6.7, 6.6, 6.6, 6.5]
ROBIN_STABLE = [4.4, 4.3, 4.5, 4.4, 4.4, 4.3]


def base_store() -> FakeStore:
    return FakeStore({"pirata": hist("pirata", PIRATA_STABLE), "robin": hist("robin", ROBIN_STABLE)})


def test_mismatch_triggers_alert():
    # Etiquetada robin pero 5.8 kg encaja mucho mejor con la tendencia de Pirata.
    alerts = crosscheck.check_assignments(CONFIG, base_store(), [visit("robin", 5.8)])
    assert len(alerts) == 1
    a = alerts[0]
    assert a.cat == "robin"
    assert a.kind == "crosscheck"
    assert a.severity == "warning"
    assert "Pirata" in a.message


def test_assignment_matches_no_alert():
    # 4.4 kg etiquetada robin: encaja con su propia tendencia → sin alerta.
    assert crosscheck.check_assignments(CONFIG, base_store(), [visit("robin", 4.4)]) == []


def test_tie_within_margin_no_alert():
    # 5.5 kg está justo en medio (Δ≈0 < margen) → no se considera contradicción.
    assert crosscheck.check_assignments(CONFIG, base_store(), [visit("robin", 5.5)]) == []


def test_insufficient_history_no_alert():
    store = FakeStore({"pirata": hist("pirata", [6.6, 6.5]),  # < min_points
                       "robin": hist("robin", ROBIN_STABLE)})
    assert crosscheck.check_assignments(CONFIG, store, [visit("robin", 5.8)]) == []


def test_disabled_no_alert():
    cfg = {**CONFIG, "crosscheck": {**CONFIG["crosscheck"], "enabled": False}}
    assert crosscheck.check_assignments(cfg, base_store(), [visit("robin", 5.8)]) == []


def test_outlier_in_history_ignored_by_mad():
    # Una lectura basura de 1.1 kg en el histórico de Robin no debe torcer su tendencia
    # ni impedir detectar la contradicción.
    store = FakeStore({
        "pirata": hist("pirata", PIRATA_STABLE),
        "robin": hist("robin", [4.4, 4.3, 1.1, 4.5, 4.4, 4.3]),
    })
    alerts = crosscheck.check_assignments(CONFIG, store, [visit("robin", 5.8)])
    assert len(alerts) == 1


def test_aggregates_per_cat():
    # Dos lecturas robin contradictorias → una sola alerta que las lista ambas.
    alerts = crosscheck.check_assignments(
        CONFIG, base_store(), [visit("robin", 5.8), visit("robin", 5.9)])
    assert len(alerts) == 1
    assert "2 lectura" in alerts[0].message


def test_empty_visits_no_alert():
    assert crosscheck.check_assignments(CONFIG, base_store(), []) == []
