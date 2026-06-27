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

**Un solo contenedor** (`supurrmente`): supervisord lanza oauth2-proxy + datasette +
tracker, cada uno con su usuario. Targets en `Makefile`:

```bash
make build          # construir la imagen
make up / down      # arrancar/parar el contenedor
make migrate        # ingerir app/deprecated/*.csv → SQLite + CSV (una vez)
make test           # unit + E2E (sin credenciales)
make test-email     # integración SMTP real (requiere .env)
make logs / shell
```

Sin `make`: `docker compose run --rm supurrmente pytest tests/ -v -m "not integration"`,
`docker compose run --rm supurrmente python src/migrate.py`. El entrypoint, si recibe un
comando, lo ejecuta y sale (no arranca el stack). Estado de los procesos:
`docker compose exec supurrmente supervisorctl status`.

Un ciclo manual real: `docker compose run --rm supurrmente python src/main.py` (si no hay
token de Whisker, manda el email de "inicia sesión" en vez de recoger datos).

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
- **Whisker por TOKEN, nunca por contraseña.** El password solo se usa una vez en el
  formulario `/whisker-login`; lo que se guarda es un token revocable
  (`/data/whisker_token.json`, 600). Usa `whisker_auth.connect_with_token`. Si falta el
  token, `run_pipeline` manda el email con el enlace (no recoge datos). Ver `whisker_auth.py`.
- **Aislamiento por usuario.** Cada proceso corre con su UID y solo lee SU fichero de
  secretos (600). `oauth2-proxy` (de cara a internet) NO debe poder leer Gmail ni el
  token. No metas secretos en el entorno global del contenedor; van por `/run/secrets/*`.
- **Tests siempre en el contenedor.** Y verdes antes de dar algo por hecho.

## Secretos (`.env`, nunca se commitea)

```
GMAIL_APP_PASSWORD=        OAUTH2_PROXY_CLIENT_ID=        OAUTH2_PROXY_COOKIE_SECRET=
FROM_EMAIL=alfred@…        OAUTH2_PROXY_CLIENT_SECRET=    OAUTH2_PROXY_REDIRECT_URL=
TO_EMAILS=joaquin@…
```

**Ya NO hay `WHISKER_USERNAME/PASSWORD`**: Whisker se autentica por token (formulario web).
`.env.age` (cifrado con `age`) SÍ se commitea. El `.env` descifrado se **monta como
fichero** (`./.env:/app/.env:ro`); el entrypoint lo reparte en `/run/secrets/{tracker,oauth}.env`
(600, por usuario) — **no** se inyecta como `env_file` (eso lo verían todos los procesos).
En la Raspi: `chmod 600 .env`. El cookie secret debe medir 16/24/32 bytes (usa 24→base64=32 chars).

## Acceso web: público vs. privado (NO romper)

**Una sola Datasette de acceso completo**, detrás de oauth2-proxy (la única puerta, `:4180`).
El candado lo pone el **proxy**, no Datasette:

- Público (sin login, `skip_auth_routes` en `oauth2-proxy.cfg`): `/` (dashboard, plugin
  `plugins/homepage.py`), `/static`, `/favicon.ico` y las 3 canned queries `.json`
  (`cat_daily`, `box_daily`, `robot_status`). El dashboard usa **estas canned queries**, nunca `?sql=`.
- Login `@gonzalez.team`: todo lo demás (tablas, SQL, `/weights`, `/-/`, `/whisker-login`).
  `oauth2-proxy` con `skip_provider_button` → directo a Google. El botón del dashboard
  (`/weights`) es el estándar de Google; `plugins/logout.py` inyecta "Cerrar sesión".

Invariante: **`skip_auth_routes` es una allow-list estricta** — solo dashboard + canned
queries. Si añades un dato al dashboard, añade su canned query Y su ruta en
`oauth2-proxy.cfg`. `tests/test_oauth_routes.py` bloquea que se afloje. Diagnósticos de
la API en `app/scripts/inspect_*.py`.

## Datos / tablas SQLite

`visits` (peso por gato), `sent_alerts` (cooldown), `api_meta` (cambios de versión),
`box_usage` (ciclos/día del robot), `robot_snapshots` (arena/cajón/online).

**Backup = CSV en el mismo volumen (`/data`) → NFS al NAS en producción (no OneDrive).**
El CSV es auto-descriptivo: cabecera `# api_version:` y rota a un fichero nuevo cuando
cambia la versión de la API (una era de API por fichero). `csv.write(visits, api_version)`.
