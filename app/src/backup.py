"""
Backup del estado al NAS, con contrato de consistencia y publicación atómica.

Principio: el dato vivo es LOCAL (bind `/data`); aquí solo se EMPUJA una copia. Un fallo
de red/NAS nunca toca el primario, y una transferencia a medias nunca pisa la última copia
buena. Flujo (ver `run_backup`):

  1. Snapshot consistente en caliente con `VACUUM INTO` + `PRAGMA integrity_check`.
  2. Traer el backup anterior del NAS y validar el **contrato de consistencia**:
     superconjunto por identidad (backup ⊆ snapshot), conteos que no decrecen,
     `max(timestamp)` que no retrocede. (No es un check de "fechas": el backfill añade
     fechas viejas legítimamente; lo que vigilamos es que no se PIERDAN filas.)
  3. Si pasa: publicar atómico por rsync (current `weights.db`/`.csv`), copia datada en
     `history/` (rotada a `retention`) y `manifest.json`.
  4. Si NO pasa: no se publica nada → cuarentena local + report para forense; el caller
     manda email.

Transporte: SSH-exec con verbos `deposit`/`fetch` contra un receptor confinado en el NAS
(clave dedicada, identidad GLN1, forced-command). Nada de rsync ni SFTP: el NAS solo hace
`cat`+`mv`. El contrato y el snapshot son lógica pura y testeable sin NAS.
"""
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import timeutils

log = logging.getLogger(__name__)

# Identidad por tabla para el chequeo de superconjunto (qué hace única a una fila).
_IDENTITY = {
    "visits": "timestamp",
    "box_usage": "day",
    "robot_snapshots": "checked_at",
    "api_meta": "checked_at",
    "sent_alerts": "fingerprint || '|' || sent_at",
}


class BackupError(Exception):
    """Fallo de backup (base)."""


class ConsistencyError(BackupError):
    """El snapshot no es superconjunto del backup previo → NUNCA publicar."""


class TransferError(BackupError):
    """Fallo de transferencia (transitorio) → reintentar antes del intervalo normal."""


# ── Lógica pura (testeable sin NAS) ───────────────────────────────────────────

def _has_table(conn: sqlite3.Connection, name: str, schema: str = "main") -> bool:
    return conn.execute(
        f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def _integrity_ok(path: str) -> bool:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as c:
            return c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    except sqlite3.Error:
        return False  # fichero ausente o que no es una BD → no íntegro


def snapshot(live_path: str, out_path: str) -> None:
    """Copia consistente en caliente del SQLite vivo. Lanza ConsistencyError si el vivo
    o el snapshot resultante no pasan integrity_check (corrupción del primario)."""
    if not _integrity_ok(live_path):
        raise ConsistencyError(f"integrity_check del vivo falló: {live_path}")
    if os.path.exists(out_path):
        os.remove(out_path)
    safe = out_path.replace("'", "''")  # VACUUM INTO no admite parámetro ligado
    with sqlite3.connect(f"file:{live_path}?mode=ro", uri=True) as c:
        c.execute(f"VACUUM INTO '{safe}'")
    if not _integrity_ok(out_path):
        raise ConsistencyError("integrity_check del snapshot falló tras VACUUM INTO")


def check_consistency(snapshot_path: str, prev_backup_path: str) -> None:
    """Contrato: el snapshot debe ser superconjunto del backup previo. Lanza
    ConsistencyError con el detalle si no lo es. Si el backup previo está corrupto,
    avisa pero NO bloquea (queremos reemplazarlo por uno bueno)."""
    if not _integrity_ok(snapshot_path):
        raise ConsistencyError("integrity_check del snapshot != ok")
    if not _integrity_ok(prev_backup_path):
        log.warning("El backup previo está corrupto; se reemplazará por el nuevo")
        return

    conn = sqlite3.connect(snapshot_path)
    try:
        conn.execute("ATTACH ? AS prev", (prev_backup_path,))
        problems = []
        for table, ident in _IDENTITY.items():
            if not (_has_table(conn, table) and _has_table(conn, table, "prev")):
                continue
            n_live = conn.execute(f"SELECT count(*) FROM main.{table}").fetchone()[0]
            n_prev = conn.execute(f"SELECT count(*) FROM prev.{table}").fetchone()[0]
            if n_live < n_prev:
                problems.append(f"{table}: snapshot {n_live} filas < backup {n_prev}")
            missing = conn.execute(
                f"SELECT count(*) FROM (SELECT {ident} AS k FROM prev.{table} "
                f"EXCEPT SELECT {ident} AS k FROM main.{table})"
            ).fetchone()[0]
            if missing:
                problems.append(f"{table}: {missing} fila(s) del backup faltan en el snapshot")

        if _has_table(conn, "visits") and _has_table(conn, "visits", "prev"):
            mx_live = conn.execute("SELECT max(timestamp) FROM main.visits").fetchone()[0]
            mx_prev = conn.execute("SELECT max(timestamp) FROM prev.visits").fetchone()[0]
            if mx_prev and (not mx_live or mx_live < mx_prev):
                problems.append(f"visits: max(timestamp) retrocede {mx_prev} → {mx_live}")

        if problems:
            raise ConsistencyError("; ".join(problems))
    finally:
        conn.close()


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(snapshot_path: str, csv_path: str) -> dict:
    """Resumen auto-descriptivo del backup: conteos, max(ts), checksums. Sirve de prueba
    forense y de referencia humana de qué se guardó."""
    conn = sqlite3.connect(snapshot_path)
    counts = {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in _IDENTITY if _has_table(conn, t)}
    mx = (conn.execute("SELECT max(timestamp) FROM visits").fetchone()[0]
          if _has_table(conn, "visits") else None)
    conn.close()
    return {
        "created_at": timeutils.now().strftime("%Y-%m-%dT%H:%M:%S%z"),
        "counts": counts,
        "max_visit_ts": mx,
        "db_sha256": _sha256(snapshot_path),
        "csv_sha256": _sha256(csv_path) if os.path.exists(csv_path) else None,
    }


# ── Transferencia: SSH-exec con verbos deposit/fetch (no rsync, no SFTP) ───────
# El NAS solo corre un receptor confinado (backup-only.sh): cat→.part→mv (atómico),
# acotado por basename a la carpeta de backups. Pasivo, atómico, sin servicios extra.
# No se cubre en tests unitarios (es integración con el NAS).

def _ssh_base(bcfg: dict) -> list:
    kh = bcfg.get("known_hosts", "/data/.ssh_known_hosts")
    return ["ssh", "-i", bcfg["ssh_key_path"], "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={kh}",
            "-o", "ConnectTimeout=20", f'{bcfg["user"]}@{bcfg["host"]}']


def _deposit(bcfg: dict, local_path: str, verb: str, name: str) -> None:
    """Sube un fichero (el NAS lo deja atómico: .part → mv). verb: deposit | deposit-history."""
    with open(local_path, "rb") as f:
        r = subprocess.run([*_ssh_base(bcfg), verb, name], stdin=f,
                           capture_output=True, timeout=180)
    if r.returncode != 0 or b"OK" not in r.stdout:
        raise TransferError(f"{verb} {name} falló (rc={r.returncode}): "
                            f"{(r.stderr or b'').decode(errors='replace').strip()}")


def _fetch(bcfg: dict, name: str, dest: str) -> bool:
    """Descarga un fichero del NAS para poder compararlo. False si aún no existe (primer
    backup); TransferError si la conexión falla (no podemos verificar → no se publica)."""
    r = subprocess.run([*_ssh_base(bcfg), "fetch", name], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise TransferError(f"fetch {name} falló (rc={r.returncode}): "
                            f"{(r.stderr or b'').decode(errors='replace').strip()}")
    if not r.stdout:
        return False  # el remoto aún no existe
    with open(dest, "wb") as f:
        f.write(r.stdout)
    return True


def _history_names(bcfg: dict) -> list:
    r = subprocess.run([*_ssh_base(bcfg), "list-history"], capture_output=True, timeout=60)
    if r.returncode != 0:
        raise TransferError(f"list-history falló (rc={r.returncode})")
    return sorted(n for n in r.stdout.decode(errors="replace").split() if n.startswith("weights-"))


def _remove_history(bcfg: dict, name: str) -> None:
    subprocess.run([*_ssh_base(bcfg), "remove-history", name], capture_output=True, timeout=60)


def _quarantine(work: Path, snap: str, prev: str, error: Exception, manifest: dict) -> Path:
    q = work / "quarantine" / timeutils.now().strftime("%Y%m%d-%H%M%S")
    q.mkdir(parents=True, exist_ok=True)
    for src, name in [(snap, "snapshot.db"), (prev, "prev_backup.db")]:
        if src and os.path.exists(src):
            shutil.copy2(src, q / name)
    (q / "report.json").write_text(json.dumps(
        {"error": str(error), "type": type(error).__name__, "manifest": manifest,
         "at": timeutils.now().strftime("%Y-%m-%dT%H:%M:%S%z")},
        indent=2, ensure_ascii=False))
    log.error("Backup en cuarentena para forense: %s", q)
    return q


# ── Orquestación ──────────────────────────────────────────────────────────────

def run_backup(config: dict) -> dict:
    """Ejecuta un backup completo. Devuelve {'ok': True, 'manifest': …} si publica,
    {'skipped': True} si está deshabilitado. Lanza ConsistencyError/TransferError en fallo
    (el caller decide email y reintento)."""
    bcfg = config.get("backup", {})
    if not bcfg.get("enabled", False):
        return {"skipped": True}

    live_db = config["storage"]["sqlite_path"]
    live_csv = config["storage"]["csv_path"]
    work = Path(live_db).parent / "_backup"
    work.mkdir(parents=True, exist_ok=True)
    snap = str(work / "weights.snapshot.db")
    prev = str(work / "weights.prev.db")

    snapshot(live_db, snap)
    manifest = build_manifest(snap, live_csv)

    # Bajar el backup actual y verificar superconjunto ANTES de tocar nada. Si la conexión
    # falla aquí, _fetch lanza TransferError → se aborta sin haber publicado nada.
    try:
        have_prev = _fetch(bcfg, "weights.db", prev)
        if have_prev:
            check_consistency(snap, prev)  # ConsistencyError → no se publica
    except ConsistencyError as e:
        q = _quarantine(work, snap, prev, e, manifest)
        raise ConsistencyError(f"{e} — datos preservados en {q}") from e

    # Publicación: cada deposit es atómico en el NAS (.part → mv).
    _deposit(bcfg, snap, "deposit", "weights.db")
    if os.path.exists(live_csv):
        _deposit(bcfg, live_csv, "deposit", "weights.csv")

    # Copia datada en history + rotación remota a 'retention'.
    stamp = timeutils.now().strftime("%Y%m%d-%H%M%S")
    _deposit(bcfg, snap, "deposit-history", f"weights-{stamp}.db")
    retention = int(bcfg.get("retention", 8))
    if retention > 0:
        for old in _history_names(bcfg)[:-retention]:
            _remove_history(bcfg, old)

    mpath = work / "manifest.json"
    mpath.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    _deposit(bcfg, str(mpath), "deposit", "manifest.json")

    log.info("Backup publicado: %s", manifest["counts"])
    return {"ok": True, "manifest": manifest}
