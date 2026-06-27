# SuPurrMente

Monitoreo del peso de mis gatos (**Pirata** y **Robin**) a partir de una
Litter-Robot 4, porque la app de Whisker solo guarda 1 semana de histórico.

Tira los datos de la LR4 cada 6h, clasifica cada visita por gato, los guarda en
SQLite + CSV (en el NAS), y manda alertas de salud por email. Dashboard con
Datasette + Chart.js.

Corre en **un solo contenedor** (oauth2-proxy + Datasette + tracker, cada proceso con
su usuario para aislar las credenciales). Whisker se autentica **por token** (un
formulario web, sin guardar la contraseña). El dashboard es público; el explorador y la
configuración van tras **login con Google `@gonzalez.team`**.

## Estructura

```
.
├── app/            # la aplicación (código, tests, Docker, config, static)
│   ├── src/        # módulos Python
│   ├── tests/      # suite (corre dentro del contenedor)
│   ├── static/     # dashboard.html
│   ├── scripts/    # diagnósticos de la API (inspect_*.py)
│   └── deprecated/ # CSV históricos para migrar
├── docs/           # arquitectura, contexto y logs de sesión
├── scripts/        # ops (encrypt-env.sh)
├── docker-compose.yml / .override.yml
├── Makefile        # targets estándar (todo en contenedor)
└── setup.sh        # despliegue en la Raspberry Pi
```

## Arranque rápido (dev)

```bash
# Credenciales (o descifra .env.age con: age --decrypt .env.age > .env)
cp .env.example .env   # rellena GMAIL_APP_PASSWORD, FROM/TO_EMAILS, OAUTH2_PROXY_*

make build             # construir la imagen
make migrate           # migrar CSV históricos (app/deprecated/*.csv) — una vez
make up                # arrancar el contenedor (3 procesos)
make test              # tests unitarios + E2E (en contenedor)

# Dashboard (sin login): http://localhost:4180/
```

El dashboard es **público** (gráficos). El explorador de la BD (`/weights`, SQL) y el
formulario para conectar Whisker (`/whisker-login`) van **tras login con Google
`@gonzalez.team`** (oauth2-proxy). La primera vez, conéctate a `/whisker-login` para
emitir el token de Whisker. Sin `make` (Windows):
`docker compose run --rm supurrmente pytest tests/`.

## Despliegue (Raspberry Pi)

```bash
bash setup.sh          # descifra .env.age, comprueba NFS, construye, migra, arranca
```

Además, una vez: registrar un OAuth Client en Google Cloud (consent screen *Internal*)
con redirect `https://<dominio>/oauth2/callback`, rellenar `OAUTH2_PROXY_*` en `.env`,
y en NPM hacer **un único forward** del dominio → `<pi>:4180` (sin custom locations:
oauth2-proxy reparte por ruta). Detalle en
[docs/sessions/2026-06-28-monolito-token.md](docs/sessions/2026-06-28-monolito-token.md).

## Documentación

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — arquitectura y módulos
- [docs/CONTEXT.md](docs/CONTEXT.md) — motivación y decisiones
- [docs/sessions/](docs/sessions/) — logs de cada sesión de desarrollo
- [CLAUDE.md](CLAUDE.md) — guía para Claude Code
