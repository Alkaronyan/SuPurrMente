#!/bin/bash
# Entrypoint del contenedor único de SuPurrMente.
#
# - Modo "comando suelto" (tests, migración): ejecuta lo que se le pase y sale.
# - Modo servicio (sin argumentos): reparte los secretos en ficheros 600 por usuario,
#   prepara /data, garantiza el esquema SQLite y arranca supervisord.
set -e

# ── Modo comando suelto: `docker compose run ... pytest|python src/migrate.py` ──
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

umask 077
ENV_FILE="${ENV_FILE:-/app/.env}"
SECRETS_DIR=/run/secrets
mkdir -p "$SECRETS_DIR"
# Traversable (o+x) pero no listable: cada usuario llega a SU fichero por nombre, pero
# los ficheros 600 siguen sin poder leerse entre usuarios (la isolación de verdad).
chmod 711 "$SECRETS_DIR"

if [ ! -f "$ENV_FILE" ]; then
    echo "[ERROR] No se encontró $ENV_FILE. Monta el .env descifrado en esa ruta." >&2
    exit 1
fi

# ── Reparto de secretos: cada proceso solo lee el suyo (600, su usuario) ───────
grep -E '^(GMAIL_APP_PASSWORD|FROM_EMAIL|TO_EMAILS)=' "$ENV_FILE" > "$SECRETS_DIR/tracker.env" || true
grep -E '^OAUTH2_PROXY_'                              "$ENV_FILE" > "$SECRETS_DIR/oauth.env"   || true
chown tracker:tracker "$SECRETS_DIR/tracker.env"; chmod 600 "$SECRETS_DIR/tracker.env"
chown oauth:oauth     "$SECRETS_DIR/oauth.env";   chmod 600 "$SECRETS_DIR/oauth.env"

# Clave SSH del backup (base64 en .env) → fichero 600 de 'tracker' (jamás de 'oauth').
BK_LINE=$(grep -E '^BACKUP_SSH_KEY_B64=' "$ENV_FILE" || true)
if [ -n "$BK_LINE" ]; then
    printf '%s' "${BK_LINE#BACKUP_SSH_KEY_B64=}" | base64 -d > "$SECRETS_DIR/backup_ssh_key"
    chown tracker:tracker "$SECRETS_DIR/backup_ssh_key"; chmod 600 "$SECRETS_DIR/backup_ssh_key"
fi

# ── /data: lo escribe 'tracker'; 'datasette' lo lee por el grupo 'data' ────────
# setgid (2750) → los ficheros heredan grupo 'data'; con umask 027 salen 640. El token
# lo fuerza el código a 600 (solo 'tracker'), así datasette no lo ve.
mkdir -p /data
chown tracker:data /data || true
chmod 2750 /data || true

# ── Esquema SQLite antes de arrancar Datasette (que falla sin BD) ──────────────
su -s /bin/bash -c 'umask 027; cd /app/src && python ensure_db.py' tracker \
    || echo "[AVISO] No se pudo precrear la BD; Datasette reintentará al levantar."

echo "[OK] Secretos repartidos y /data listo. Arrancando supervisord…"
exec supervisord -c /etc/supervisor/conf.d/supervisord.conf
