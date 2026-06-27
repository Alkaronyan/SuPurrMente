"""Tests for the API contract validator and the version registry.

These guard the 'tell me when Whisker changes the API again' behaviour.
"""
import api_contract
from storage.sqlite_store import SQLiteStore

CONFIG = {
    "cats": {"pirata": {"seed_weight_kg": 6.6}, "robin": {"seed_weight_kg": 4.4}},
    "api_health": {"max_weight_ratio": 1.8, "min_weight_ratio": 0.55},
}
KNOWN = {"pirata", "robin"}


def pet(name, cat, readings, error=None, ok_shape=True):
    return {"name": name, "cat": cat, "readings_kg": readings,
            "error": error, "ok_shape": ok_shape}


class TestValidate:
    def test_healthy_returns_no_issues(self):
        pets = [pet("Pirata", "pirata", [6.4, 6.6, 6.5]),
                pet("Robin", "robin", [4.3, 4.4, 4.5])]
        assert api_contract.validate(KNOWN, pets, CONFIG) == []

    def test_no_pets_is_an_issue(self):
        issues = api_contract.validate(KNOWN, [], CONFIG)
        assert len(issues) == 1
        assert "ninguna mascota" in issues[0]

    def test_missing_expected_cat(self):
        pets = [pet("Pirata", "pirata", [6.5])]
        issues = api_contract.validate(KNOWN, pets, CONFIG)
        assert any("robin" in i for i in issues)

    def test_history_error_surfaces(self):
        pets = [pet("Pirata", "pirata", [], error="AttributeError: no fetch_weight_history"),
                pet("Robin", "robin", [4.4])]
        issues = api_contract.validate(KNOWN, pets, CONFIG)
        assert any("Error leyendo el historial de Pirata" in i for i in issues)

    def test_bad_shape_surfaces(self):
        pets = [pet("Pirata", "pirata", [6.5], ok_shape=False),
                pet("Robin", "robin", [4.4])]
        issues = api_contract.validate(KNOWN, pets, CONFIG)
        assert any("formato inesperado" in i for i in issues)

    def test_all_empty_histories_is_an_issue(self):
        pets = [pet("Pirata", "pirata", []), pet("Robin", "robin", [])]
        issues = api_contract.validate(KNOWN, pets, CONFIG)
        assert any("ningún historial de peso" in i for i in issues)

    def test_unit_change_detected_for_both_cats(self):
        # If weights came back in lbs (unconverted): ~×2.2 off seed for BOTH cats.
        pets = [pet("Pirata", "pirata", [14.0, 14.6, 14.8]),   # vs 6.6 → ×2.2
                pet("Robin", "robin", [9.4, 9.7, 10.1])]       # vs 4.4 → ×2.2
        issues = api_contract.validate(KNOWN, pets, CONFIG)
        assert sum("cambió la unidad" in i for i in issues) == 2

    def test_light_cat_unit_change_not_missed(self):
        # The key case an absolute band would miss: Robin in lbs still < 12.
        pets = [pet("Pirata", "pirata", [6.5]), pet("Robin", "robin", [9.7])]
        issues = api_contract.validate(KNOWN, pets, CONFIG)
        assert any("Robin" in i and "unidad" in i for i in issues)

    def test_normal_weights_within_ratio_pass(self):
        pets = [pet("Pirata", "pirata", [6.4, 6.6, 6.8]),
                pet("Robin", "robin", [4.2, 4.4, 4.6])]
        assert api_contract.validate(KNOWN, pets, CONFIG) == []

    def test_one_outlier_does_not_trip_median(self):
        pets = [pet("Pirata", "pirata", [6.5, 6.6, 6.4, 0.3]),  # median still ~6.5
                pet("Robin", "robin", [4.3, 4.4, 4.5])]
        assert api_contract.validate(KNOWN, pets, CONFIG) == []


class TestVersionRegistry:
    def _store(self, tmp_path):
        return SQLiteStore({"storage": {"sqlite_path": str(tmp_path / "m.db")}})

    def test_first_record_is_baseline_no_alert(self, tmp_path):
        store = self._store(tmp_path)
        change = store.record_api_meta("ESP: 1.1.75", "2024.0.0", "Litter-Robot 4", "LR4C1")
        assert change is None

    def test_no_change_returns_none(self, tmp_path):
        store = self._store(tmp_path)
        store.record_api_meta("ESP: 1.1.75", "2024.0.0", "Litter-Robot 4", "LR4C1")
        change = store.record_api_meta("ESP: 1.1.75", "2024.0.0", "Litter-Robot 4", "LR4C1")
        assert change is None

    def test_firmware_change_detected(self, tmp_path):
        store = self._store(tmp_path)
        store.record_api_meta("ESP: 1.1.75", "2024.0.0", "Litter-Robot 4", "LR4C1")
        change = store.record_api_meta("ESP: 1.2.0", "2024.0.0", "Litter-Robot 4", "LR4C1")
        assert change == {"field": "firmware", "old": "ESP: 1.1.75", "new": "ESP: 1.2.0"}

    def test_library_change_detected(self, tmp_path):
        store = self._store(tmp_path)
        store.record_api_meta("ESP: 1.1.75", "2024.0.0", "Litter-Robot 4", "LR4C1")
        change = store.record_api_meta("ESP: 1.1.75", "2025.1.0", "Litter-Robot 4", "LR4C1")
        assert change["field"] == "library_version"
