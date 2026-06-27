# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Qué es

SuPurrMente monitoriza el peso de dos gatos — **Pirata** (~6.6 kg) y **Robin**
(~4.4 kg) — tirando datos de una Litter-Robot 4 vía `pylitterbot`. Cada visita da
una lectura de peso ya identificada por gato; se guarda en SQLite (primario) + CSV
(backup NAS) y se mandan alertas de salud por email. La app de Whisker solo guarda
1 semana; esto da histórico indefinido.

Arquitectura completa en [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Historia y
aprendizajes en [docs/sessions/](docs/sessions/).

## Estructura

- `app/` — la aplicación: `src/`, `tests/`, `static/`, `Dockerfile`, `config.yml`,
  `datasette.yml`, `requirements*.txt`, `scripts/` (diagnósticos de la API),
  `deprecated/` (CSV históricos).
- `docs/` — documentación y logs de sesión.
- `scripts/` — ops (`encrypt-env.sh`). Raíz: compose, Makefile, setup.sh, `.env*`.

## Comandos

Todo corre **dentro del contenedor** (idéntico en dev y Raspi). Targets en `Makefile`:

```bash
make build          # construir imágenes
make up / down      # servicios (tracker=cron, datasette=:8001)
make migrate        # ingerir app/deprecated/*.csv → SQLite + CSV (una vez)
make test           # unit + E2E (sin credenciales)
make test-email     # integración SMTP real (requiere .env)
make test-all       # todo
make logs / shell
```

Sin `make`: `docker compose run --rm tracker pytest tests/ -v -m "not integration"`,
`docker compose run --rm tracker python src/migrate.py`, etc. (las rutas dentro del
contenedor siguen siendo `/app/src`, `/app/tests` — el contexto de build es `./app`).

Un ciclo manual real: `docker compose run --rm tracker python src/main.py`.

## Invariantes que NO debes romper

- **Idempotencia total.** Reejecutar cualquier paso (ciclo, migración, alertas),
  incluso tras un fallo, debe converger al mismo estado. SQLite usa
  `INSERT OR IGNORE`; CSV dedup por timestamp; migración dedup difuso ±120s;
  alertas con cooldown de 24h. Los tests en `tests/test_idempotency.py` lo bloquean.
- **Zona horaria local Madrid.** Usa siempre `timeutils.now()` / `timeutils.to_local()`,
  **nunca** `datetime.now(timezone.utc)`. La API llega en UTC y se convierte; el CSV
  ya es local. Necesita el paquete `tzdata`.
- **El gato lo da la API.** El peso vive en `account.pets[*].weight_history`, en
  **libras** (×0.453592), ya por gato. `get_activity_history()` NO trae pesos. El
  clasificador solo valida en vivo (`classify_known`); clasifica de verdad solo en
  la migración histórica.
- **Resiliencia de API.** Cada ciclo valida el contrato (`api_contract.py`) y
  registra firmware/versión (`api_meta`); una desviación manda email crítico. Si
  cambias el fetcher, mantén estos chequeos.
- **Tests siempre en el contenedor.** Y verdes antes de dar algo por hecho.

## Secretos (`.env`, nunca se commitea)

```
WHISKER_USERNAME=        GMAIL_APP_PASSWORD=
WHISKER_PASSWORD=        FROM_EMAIL=alfred@gonzalez.team
                         TO_EMAILS=joaquin@gonzalez.team
```

`.env.age` (cifrado con `age`) SÍ se commitea. Los emails se leen de env vars, NO de
`config.yml`. En la Raspi: `chmod 600 .env`.

## Datos / tablas SQLite

`visits` (peso por gato), `sent_alerts` (cooldown), `api_meta` (cambios de versión),
`box_usage` (ciclos/día del robot), `robot_snapshots` (arena/cajón/online). El
dashboard (Datasette :8001) consulta vía SQL. Diagnósticos de la API en
`app/scripts/inspect_*.py` (se ejecutan copiándolos a `app/src/` dentro del contenedor).

**Backup = CSV en el mismo volumen (`/data`) → NFS al NAS en producción (no OneDrive).**
El CSV es auto-descriptivo: cabecera `# api_version:` y rota a un fichero nuevo cuando
cambia la versión de la API (una era de API por fichero). `csv.write(visits, api_version)`.
