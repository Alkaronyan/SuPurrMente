"""Tests de backup: snapshot consistente + contrato de superconjunto + manifest.

La transferencia rsync/SSH al NAS es integración (no se cubre aquí); lo que se prueba es
la lógica pura que decide si un backup es seguro de publicar."""
import sqlite3

import pytest

import backup


def make_db(path, timestamps):
    """SQLite mínimo con la tabla visits y los timestamps dados."""
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE visits (id INTEGER PRIMARY KEY AUTOINCREMENT, "
              "timestamp TEXT UNIQUE, cat TEXT, weight_kg REAL)")
    c.executemany("INSERT INTO visits (timestamp, cat, weight_kg) VALUES (?, 'robin', 4.4)",
                  [(t,) for t in timestamps])
    c.commit()
    c.close()


T1, T2, T3, T4 = ("2026-01-01T10:00:00Z", "2026-03-01T10:00:00Z",
                  "2026-05-01T10:00:00Z", "2026-06-01T10:00:00Z")


def test_snapshot_creates_valid_consistent_copy(tmp_path):
    live = tmp_path / "live.db"
    out = tmp_path / "snap.db"
    make_db(str(live), [T1, T2, T3])
    backup.snapshot(str(live), str(out))
    assert out.exists()
    rows = sqlite3.connect(str(out)).execute("SELECT count(*) FROM visits").fetchone()[0]
    assert rows == 3


def test_consistency_passes_when_superset(tmp_path):
    prev = tmp_path / "prev.db"
    snap = tmp_path / "snap.db"
    make_db(str(prev), [T1, T2])
    make_db(str(snap), [T1, T2, T3])           # añade datos nuevos
    backup.check_consistency(str(snap), str(prev))   # no lanza


def test_consistency_allows_backfill_of_older_dates(tmp_path):
    # El snapshot añade una fecha MÁS ANTIGUA que las del backup (migración/backfill).
    # Debe pasar: lo que importa es no PERDER filas, no las fechas.
    prev = tmp_path / "prev.db"
    snap = tmp_path / "snap.db"
    make_db(str(prev), [T2, T3])
    make_db(str(snap), [T1, T2, T3])           # T1 es anterior a todo lo del backup
    backup.check_consistency(str(snap), str(prev))   # no lanza


def test_consistency_fails_when_rows_missing(tmp_path):
    # El snapshot ha PERDIDO una fila que el backup tenía → nunca publicar.
    prev = tmp_path / "prev.db"
    snap = tmp_path / "snap.db"
    make_db(str(prev), [T1, T2, T3])
    make_db(str(snap), [T1, T2])               # falta T3
    with pytest.raises(backup.ConsistencyError) as e:
        backup.check_consistency(str(snap), str(prev))
    assert "falta" in str(e.value) or "faltan" in str(e.value)


def test_consistency_fails_when_count_shrinks(tmp_path):
    prev = tmp_path / "prev.db"
    snap = tmp_path / "snap.db"
    make_db(str(prev), [T1, T2, T3, T4])
    make_db(str(snap), [T1])                    # menos filas y faltan
    with pytest.raises(backup.ConsistencyError):
        backup.check_consistency(str(snap), str(prev))


def test_consistency_skips_when_prev_corrupt(tmp_path):
    # Un backup previo corrupto NO debe bloquear: se reemplaza por uno bueno.
    prev = tmp_path / "prev.db"
    snap = tmp_path / "snap.db"
    make_db(str(snap), [T1, T2])
    prev.write_bytes(b"esto no es una base de datos sqlite")
    backup.check_consistency(str(snap), str(prev))   # no lanza


def test_build_manifest(tmp_path):
    snap = tmp_path / "snap.db"
    make_db(str(snap), [T1, T2, T3])
    m = backup.build_manifest(str(snap), str(tmp_path / "noexiste.csv"))
    assert m["counts"]["visits"] == 3
    assert m["max_visit_ts"] == T3
    assert len(m["db_sha256"]) == 64
    assert m["csv_sha256"] is None


def test_run_backup_disabled_returns_skipped():
    assert backup.run_backup({"backup": {"enabled": False}}) == {"skipped": True}


def test_restore_skips_when_db_has_data(tmp_path):
    # Idempotencia: si la BD local ya tiene datos, NO se restaura (la local manda).
    db = tmp_path / "weights.db"
    make_db(str(db), [T1, T2])
    cfg = {"storage": {"sqlite_path": str(db), "csv_path": str(tmp_path / "w.csv")},
           "backup": {"enabled": True}}
    assert "skipped" in backup.restore_if_missing(cfg)


def test_restore_proceeds_when_db_empty(tmp_path, monkeypatch):
    # Una BD vacía (0 visitas, como la que crea ensure_db) NO debe bloquear la restauración:
    # con backup deshabilitado, el guard de emptiness se pasa y se llega al de 'enabled'.
    db = tmp_path / "weights.db"
    make_db(str(db), [])  # tabla visits pero sin filas
    cfg = {"storage": {"sqlite_path": str(db), "csv_path": str(tmp_path / "w.csv")},
           "backup": {"enabled": False}}
    assert backup.restore_if_missing(cfg) == {"skipped": "backup deshabilitado"}


def test_restore_skips_when_backup_disabled(tmp_path):
    cfg = {"storage": {"sqlite_path": str(tmp_path / "nope.db"), "csv_path": str(tmp_path / "w.csv")},
           "backup": {"enabled": False}}
    assert "skipped" in backup.restore_if_missing(cfg)
