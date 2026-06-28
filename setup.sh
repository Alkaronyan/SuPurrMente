#!/bin/bash
# SuPurrMente — script de instalación y puesta en marcha
# Uso: bash setup.sh
set -e

BOLD="\033[1m"
RESET="\033[0m"
OK="[OK]"
WARN="[AVISO]"
ERR="[ERROR]"

echo -e "${BOLD}=== SuPurrMente — Setup ===${RESET}"
echo ""

# ── 1. Dependencias del HOST (age + Docker) ──────────────────────────────────
# SOLO dependencias de host. Python, pip y las librerías viven DENTRO del
# contenedor; este script NUNCA instala Python en el host (nada de copias sueltas).
# Idempotente: cada paquete se instala solo si su comando aún no existe.
SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi
APT_UPDATED=0

apt_install() {
    if ! command -v apt-get &>/dev/null; then
        echo "${ERR} Sistema sin apt. Instala manualmente: $* — y reintenta."
        exit 1
    fi
    if [ "$APT_UPDATED" -eq 0 ]; then
        echo "      apt-get update..."
        $SUDO apt-get update -qq
        APT_UPDATED=1
    fi
    $SUDO apt-get install -y "$@"
}

ensure_cmd() {  # ensure_cmd <comando> <paquete-apt>
    if command -v "$1" &>/dev/null; then
        echo "${OK} $1 ya presente ($(command -v "$1"))"
    else
        echo "${WARN} $1 no encontrado — instalando '$2'..."
        apt_install "$2"
        if ! command -v "$1" &>/dev/null; then
            echo "${ERR} '$1' sigue ausente tras instalar '$2'."
            exit 1
        fi
        echo "${OK} $1 instalado"
    fi
}

echo "Comprobando dependencias del host (no se toca Python)..."
ensure_cmd age age
ensure_cmd docker docker.io
# 'docker compose' v2 es un plugin, no un binario suelto: se verifica aparte.
if docker compose version &>/dev/null; then
    echo "${OK} docker compose (v2) ya presente"
else
    echo "${WARN} 'docker compose' no disponible — instalando 'docker-compose-plugin'..."
    apt_install docker-compose-plugin
    if ! docker compose version &>/dev/null; then
        echo "${ERR} 'docker compose' sigue sin funcionar; instálalo manualmente."
        exit 1
    fi
    echo "${OK} docker compose instalado"
fi

# ── 2. Descifrar .env ────────────────────────────────────────────────────────
if [ ! -f .env ]; then
    if [ -f .env.age ]; then
        # Hint OPCIONAL de la passphrase, leído de un .env.hint LOCAL (gitignored). Nunca
        # va en el repo (es público): si quieres verlo aquí, crea ./.env.hint con tu pista.
        HINT=""
        if [ -f .env.hint ]; then HINT=" ($(tr -d '\r\n' < .env.hint))"; fi
        echo "Credenciales cifradas detectadas. Introduce la contraseña maestra${HINT}:"
        age --decrypt .env.age > .env
        chmod 600 .env
        echo "${OK} Credenciales descifradas y guardadas en .env (600)"
    else
        echo "${ERR} No hay .env ni .env.age. Crea un .env con estas claves:"
        echo "        GMAIL_APP_PASSWORD  FROM_EMAIL  TO_EMAILS"
        echo "        OAUTH2_PROXY_CLIENT_ID  OAUTH2_PROXY_CLIENT_SECRET"
        echo "        OAUTH2_PROXY_COOKIE_SECRET  OAUTH2_PROXY_REDIRECT_URL"
        echo "      Luego cífralo con: bash scripts/encrypt-env.sh"
        exit 1
    fi
else
    chmod 600 .env
    echo "${OK} Credenciales: .env existe con permisos 600"
fi

# ── 3. Datos locales (bind ./data) ───────────────────────────────────────────
# El estado vivo (SQLite + CSV) es LOCAL: el contenedor monta ./data en /data (SQLite no
# debe vivir sobre NFS). El NAS solo recibe la COPIA DE SEGURIDAD (push por SSH; el job de
# backup la empuja cada few días). En un despliegue nuevo, restaura ./data/weights.db desde
# el NAS antes de arrancar para no empezar de cero. Ver docs/DEPLOY.md.
mkdir -p data
echo "${OK} Datos locales en ./data (la copia de seguridad va al NAS por SSH)"

# ── 4. Construir imágenes Docker ─────────────────────────────────────────────
echo ""
echo "Construyendo imágenes Docker..."
docker compose build
echo "${OK} Imágenes construidas"

# ── 5. Migración de datos históricos (solo si la BD local no existe) ─────────
DB_PATH="data/weights.db"
if [ ! -f "$DB_PATH" ]; then
    echo ""
    echo "${WARN} No hay ./data/weights.db. Restaura el backup del NAS, o copia los CSV"
    echo "        históricos a app/deprecated/ para migrarlos ahora (si no, BD vacía):"
    docker compose run --rm supurrmente python src/migrate.py || true
    echo "${OK} Migración intentada"
else
    echo "${OK} Base de datos local existente — se omite la migración"
fi

# ── 6. Iniciar servicios ─────────────────────────────────────────────────────
echo ""
echo "Iniciando servicios..."
docker compose up -d
echo "${OK} Servicios iniciados"

# ── 7. Resumen ───────────────────────────────────────────────────────────────
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
echo ""
echo -e "${BOLD}Sistema en marcha${RESET}"
echo "  Dashboard          : https://supurrmente.gonzalez.team/            (público)"
echo "  Explorador / login : https://supurrmente.gonzalez.team/weights     (login Google @gonzalez.team)"
echo "  Conectar Whisker   : https://supurrmente.gonzalez.team/whisker-login"
echo "  Procesos           : docker compose exec supurrmente supervisorctl status"
echo "  Logs               : docker compose logs -f supurrmente"
echo ""
echo "  NPM: un único forward del dominio → ${LOCAL_IP}:4180  (sin custom locations)."
echo "       oauth2-proxy reparte por ruta y decide qué es público."
