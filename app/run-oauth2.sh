#!/bin/bash
# Proceso oauth2-proxy (usuario 'oauth', el único de cara a internet). Carga SOLO sus
# secretos (Google + cookie). No tiene acceso a /data ni a los secretos del tracker.
set -e

# Carga KEY=VALUE sin evaluarlo como shell.
while IFS= read -r line; do
  [ -z "$line" ] && continue
  case "$line" in \#*) continue ;; esac
  export "$line"
done < /run/secrets/oauth.env

exec oauth2-proxy --config /app/oauth2-proxy.cfg
