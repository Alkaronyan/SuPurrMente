# Binario de oauth2-proxy desde su imagen oficial (multi-arch: amd64 dev / arm64 Pi).
FROM quay.io/oauth2-proxy/oauth2-proxy:v7.6.0 AS oauth2

FROM python:3.11-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends supervisor tini \
    && rm -rf /var/lib/apt/lists/*

# Usuarios sin login, UIDs fijos (estables para los permisos del volumen /data).
# 'tracker' y 'datasette' comparten el grupo 'data' (datasette lee la BD; el token,
# 600, queda solo para tracker). 'oauth' va aparte: el proceso de cara a internet no
# puede leer ningún secreto del tracker.
RUN groupadd -g 10010 data \
 && groupadd -g 10001 tracker   && useradd -u 10001 -g tracker   -G data -M -s /usr/sbin/nologin tracker \
 && groupadd -g 10002 datasette && useradd -u 10002 -g datasette -G data -M -s /usr/sbin/nologin datasette \
 && groupadd -g 10003 oauth     && useradd -u 10003 -g oauth            -M -s /usr/sbin/nologin oauth

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=oauth2 /bin/oauth2-proxy /usr/local/bin/oauth2-proxy

COPY src/ src/
COPY tests/ tests/
COPY static/ static/
COPY plugins/ plugins/
COPY datasette.yml oauth2-proxy.cfg pyproject.toml ./
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY entrypoint.sh run-tracker.sh run-datasette.sh run-oauth2.sh ./
RUN chmod +x entrypoint.sh run-tracker.sh run-datasette.sh run-oauth2.sh

# tini como PID 1 (reaparenta zombies); el entrypoint reparte secretos y lanza supervisord.
ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
