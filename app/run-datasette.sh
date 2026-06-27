#!/bin/bash
# Proceso datasette (usuario 'datasette'): escucha SOLO en 127.0.0.1 (solo lo alcanza
# oauth2-proxy). Sin secretos. Lee la BD por el grupo 'data'; el token (600) no lo ve.
set -e
exec python -m datasette /data/weights.db \
  --host 127.0.0.1 --port 8081 \
  --metadata /app/datasette.yml \
  --plugins-dir /app/plugins \
  --static static:/app/static
