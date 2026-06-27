# SuPurrMente — comandos estándar (todos corren dentro del contenedor)
#
# Uso (Linux/macOS/Pi/Git-Bash):   make <target>
# Uso en Windows PowerShell:       docker compose run --rm supurrmente <comando>

.PHONY: help build up down restart migrate \
        test test-unit test-e2e test-email test-all \
        logs shell

DC  = docker compose
SVC = supurrmente
RUN = $(DC) run --rm $(SVC)

# ── Ayuda ────────────────────────────────────────────────────────────────────
help:
	@echo ""
	@echo "  SuPurrMente — targets disponibles"
	@echo ""
	@echo "  make build          Construir la imagen Docker"
	@echo "  make up             Iniciar el contenedor en background"
	@echo "  make down           Detenerlo"
	@echo "  make restart        down + up"
	@echo "  make migrate        Migrar CSVs históricos a SQLite"
	@echo ""
	@echo "  make test           Tests unitarios + E2E (sin credenciales)"
	@echo "  make test-email     Test de integración de email (requiere .env)"
	@echo "  make test-all       Todos los tests incluido el de email"
	@echo ""
	@echo "  make logs           Logs del contenedor en tiempo real"
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
	$(RUN) python src/migrate.py

# ── Tests (todos corren DENTRO del contenedor) ────────────────────────────────
test:
	$(RUN) pytest tests/ -v -m "not integration"

test-unit:
	$(RUN) pytest tests/ -v -m "not integration and not e2e" \
	    --ignore=tests/test_e2e.py --ignore=tests/test_email_integration.py

test-e2e:
	$(RUN) pytest tests/test_e2e.py -v

test-email:
	$(RUN) pytest tests/test_email_integration.py -v -m integration

test-all:
	$(RUN) pytest tests/ -v -m "integration or not integration"

# ── Observabilidad ───────────────────────────────────────────────────────────
logs:
	$(DC) logs -f $(SVC)

shell:
	$(RUN) bash
