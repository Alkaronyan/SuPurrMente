#!/bin/bash
# Proceso tracker (usuario 'tracker'): uvicorn (formulario /whisker-login) + scheduler.
# Carga SOLO sus secretos (Gmail). umask 027 → la BD/CSV salen 640 (grupo 'data' las lee).
set -e
umask 027

# Carga KEY=VALUE sin evaluarlo como shell (el app-password de Gmail lleva espacios).
while IFS= read -r line; do
  [ -z "$line" ] && continue
  case "$line" in \#*) continue ;; esac
  export "$line"
done < /run/secrets/tracker.env

cd /app/src
exec python -m uvicorn webapp:app --host 127.0.0.1 --port 8082 --no-access-log
