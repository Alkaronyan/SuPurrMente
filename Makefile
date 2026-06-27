# SuPurrMente — comandos estándar (todos corren dentro del contenedor)
#
# Uso (Linux/macOS/Pi/Git-Bash):   make <target>
# Uso en Windows PowerShell:       docker compose run --rm tracker <comando>
#
# Instalar make en Windows:  winget install GnuWin32.Make
#                            o usar Git Bash (ya incluye make)

.PHONY: help build up down restart migrate \
        test test-unit test-e2e test-email test-all \
        logs logs-datasette shell

DC      = docker compose
TRACKER = $(DC) run --rm tracker

# ── Ayuda ────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  SuPurrMente — targets disponibles"
	@echo ""
	@echo "  make build          Construir las imágenes Docker"
	@echo "  make up             Iniciar servicios en background"
	@echo "  make down           Detener servicios"
	@echo "  make restart        down + up"
	@echo "  make migrate        Migrar CSVs históricos a SQLite"
	@echo ""
	@echo "  make test           Tests unitarios + E2E (sin credenciales)"
	@echo "  make test-unit      Solo tests unitarios"
	@echo "  make test-e2e       Solo test E2E de Datasette"
	@echo "  make test-email     Test de integración de email (requiere .env)"
	@echo "  make test-all       Todos los tests incluido el de email"
	@echo ""
	@echo "  make logs           Logs del tracker en tiempo real"
	@echo "  make shell          Shell interactivo dentro del contenedor"
	@echo ""

# ── Ciclo de vida ─────────────────────────────────────────────────────────────
build:
	$(DC) build

up:
	$(DC) up -d

down:
	$(DC) down

restart: down up

# ── Migración ─────────────────────────────────────────────────────────────────
migrate:
	$(TRACKER) python src/migrate.py

# ── Tests (todos corren DENTRO del contenedor) ────────────────────────────────
# Estándar: unitarios + E2E, sin marcar integración
test:
	$(TRACKER) pytest tests/ -v -m "not integration"

test-unit:
	$(TRACKER) pytest tests/ -v -m "not integration and not e2e" \
	    --ignore=tests/test_e2e.py --ignore=tests/test_email_integration.py

test-e2e:
	$(TRACKER) pytest tests/test_e2e.py -v

# Test de integración real: envía un email por SMTP y verifica que no falla
test-email:
	$(TRACKER) pytest tests/test_email_integration.py -v -m integration

# Todo (incluyendo email real — requiere .env con credenciales)
test-all:
	$(TRACKER) pytest tests/ -v -m "integration or not integration"

# ── Observabilidad ───────────────────────────────────────────────────────────
logs:
	$(DC) logs -f tracker

logs-datasette:
	$(DC) logs -f datasette

# ── Desarrollo ───────────────────────────────────────────────────────────────
shell:
	$(TRACKER) bash
