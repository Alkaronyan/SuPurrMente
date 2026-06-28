"""Restaura la BD del NAS si falta en `/data` (seed de un despliegue nuevo). Idempotente:
no pisa una BD existente. Usa la clave dedicada GLN1 (verbo `fetch`).

Se ejecuta en **modo comando** (`docker compose run --rm supurrmente python src/restore.py`),
donde el entrypoint NO reparte los secretos a `/run/secrets`; por eso la clave del backup se
lee del `.env` montado en `/app/.env` y se deja en un fichero temporal 600.
"""
import base64
import os
from pathlib import Path

import backup
from main import load_config


def _decode_key(dst="/tmp/backup_key"):
    """Saca BACKUP_SSH_KEY_B64 del .env montado a un fichero 600. None si no está."""
    env = Path("/app/.env")
    if not env.exists():
        return None
    for line in env.read_text().splitlines():
        if line.startswith("BACKUP_SSH_KEY_B64="):
            data = base64.b64decode(line.split("=", 1)[1].strip())
            fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            os.write(fd, data)
            os.close(fd)
            return dst
    return None


def main() -> None:
    cfg = load_config()
    # En el contenedor de servicio (exec) la clave ya está repartida (600, tracker); úsala.
    # En modo comando no, así que la sacamos del .env montado.
    keypath = cfg["backup"].get("ssh_key_path")
    if not (keypath and os.path.exists(keypath)):
        key = _decode_key()
        if key:
            cfg["backup"]["ssh_key_path"] = key
            cfg["backup"]["known_hosts"] = "/tmp/known_hosts"
    print(backup.restore_if_missing(cfg))


if __name__ == "__main__":
    main()
