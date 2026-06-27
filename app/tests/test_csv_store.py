"""Backup CSV: API-version header, rotation on API change, legacy stamping, dedup."""
from datetime import timedelta

import timeutils
from classifier import ClassifiedVisit
from storage.csv_store import CsvStore

NOW = timeutils.now().replace(microsecond=0)
V1 = "ESP: 1.1.75 | pylitterbot 2025.5.0"
V2 = "ESP: 1.2.0 | pylitterbot 2025.6.0"


def visit(cat, kg, offset_h=0):
    return ClassifiedVisit(timestamp=NOW - timedelta(hours=offset_h), cat=cat,
                           weight_kg=kg, raw_weight_kg=kg, confidence=1.0)


def store(tmp_path):
    return CsvStore({"storage": {"csv_path": str(tmp_path / "weights.csv")}})


def read(tmp_path, name="weights.csv"):
    return (tmp_path / name).read_text(encoding="utf-8")


def archives(tmp_path):
    return sorted(p.name for p in tmp_path.glob("weights_*.csv"))


class TestHeaderAndDedup:
    def test_fresh_write_has_version_header(self, tmp_path):
        store(tmp_path).write([visit("pirata", 6.5)], api_version=V1)
        text = read(tmp_path)
        assert "# SuPurrMente backup CSV" in text
        assert f"# api_version: {V1}" in text
        assert "timestamp,cat,weight_kg,raw_weight_kg,confidence" in text

    def test_same_version_appends_and_dedups(self, tmp_path):
        s = store(tmp_path)
        s.write([visit("pirata", 6.5), visit("robin", 4.3, 1)], api_version=V1)
        s.write([visit("pirata", 6.5), visit("robin", 4.4, 2)], api_version=V1)  # 1 dup, 1 new
        data = [ln for ln in read(tmp_path).splitlines()
                if ln and not ln.startswith("#") and not ln.startswith("timestamp")]
        assert len(data) == 3
        assert archives(tmp_path) == []  # no rotation


class TestRotation:
    def test_version_change_rotates(self, tmp_path):
        s = store(tmp_path)
        s.write([visit("pirata", 6.5)], api_version=V1)
        s.write([visit("robin", 4.3, 1)], api_version=V2)  # API changed

        assert len(archives(tmp_path)) == 1            # old file archived
        active = read(tmp_path)
        assert f"# api_version: {V2}" in active         # new active on V2
        assert "robin" in active and "pirata" not in active.split("\n", 4)[-1]

    def test_archive_keeps_old_data(self, tmp_path):
        s = store(tmp_path)
        s.write([visit("pirata", 6.5)], api_version=V1)
        s.write([visit("robin", 4.3, 1)], api_version=V2)
        archived = read(tmp_path, archives(tmp_path)[0])
        assert f"# api_version: {V1}" in archived
        assert "pirata" in archived


class TestLegacyAndUnknown:
    def test_legacy_file_gets_stamped(self, tmp_path):
        # A pre-versioning file: just column header + a row, no metadata.
        p = tmp_path / "weights.csv"
        p.write_text("timestamp,cat,weight_kg,raw_weight_kg,confidence\n"
                     "2026-01-01T10:00:00Z,pirata,6.5,6.5,1.0\n", encoding="utf-8")
        store(tmp_path).write([visit("robin", 4.3)], api_version=V1)
        text = read(tmp_path)
        assert f"# api_version: {V1}" in text
        assert "2026-01-01T10:00:00Z" in text  # original row preserved
        assert archives(tmp_path) == []        # stamped in place, not rotated

    def test_unknown_is_pinned_without_rotation(self, tmp_path):
        s = store(tmp_path)
        s.write([visit("pirata", 6.5)], api_version=None)   # migration: unknown
        assert "# api_version: desconocida" in read(tmp_path)
        s.write([visit("robin", 4.3, 1)], api_version=V1)   # first real version
        text = read(tmp_path)
        assert f"# api_version: {V1}" in text
        assert "desconocida" not in text
        assert archives(tmp_path) == []                      # pinned, not rotated

    def test_migration_then_unknown_again_no_rotation(self, tmp_path):
        s = store(tmp_path)
        s.write([visit("pirata", 6.5)], api_version=None)
        s.write([visit("robin", 4.3, 1)], api_version=None)  # still unknown
        assert archives(tmp_path) == []
