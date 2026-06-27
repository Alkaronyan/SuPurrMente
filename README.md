# SuPurrMente

Monitoreo del peso de mis gatos (**Pirata** y **Robin**) a partir de una
Litter-Robot 4, porque la app de Whisker solo guarda 1 semana de histórico.

Tira los datos de la LR4 cada 6h, clasifica cada visita por gato, los guarda en
SQLite + CSV (en el NAS), y manda alertas de salud por email. Dashboard con
Datasette + Chart.js.

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
cp .env.example .env   # y rellena WHISKER_*, GMAIL_APP_PASSWORD, FROM/TO_EMAILS

make build             # construir imágenes
make migrate           # migrar CSV históricos (app/deprecated/*.csv) — una vez
make up                # levantar tracker (cron) + datasette
make test              # tests unitarios + E2E (en contenedor)

# Dashboard: http://localhost:8001/static/dashboard.html
```

Sin `make` (Windows): `docker compose run --rm tracker pytest tests/` etc.

## Despliegue (Raspberry Pi)

```bash
bash setup.sh          # descifra .env.age, comprueba NFS, construye, migra, arranca
```

## Documentación

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — arquitectura y módulos
- [docs/CONTEXT.md](docs/CONTEXT.md) — motivación y decisiones
- [docs/sessions/](docs/sessions/) — logs de cada sesión de desarrollo
- [CLAUDE.md](CLAUDE.md) — guía para Claude Code
