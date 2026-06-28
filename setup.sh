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
        echo "Credenciales cifradas detectadas. Introduce la contraseña maestra:"
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

# ── 3. Verificar montaje NFS ─────────────────────────────────────────────────
NFS_MOUNT="/mnt/nas/cat-weights"
if mountpoint -q "$NFS_MOUNT" 2>/dev/null; then
    echo "${OK} NFS montado en $NFS_MOUNT"
else
    echo "${WARN} $NFS_MOUNT no está montado."
    echo "      Para montarlo permanentemente, añade a /etc/fstab:"
    echo "        <IP-NAS>:/volume1/cat-weights  $NFS_MOUNT  nfs  defaults,_netdev  0  0"
    echo "      Luego: sudo mkdir -p $NFS_MOUNT && sudo mount -a"
    echo ""
    read -r -p "      Continuar sin NFS (los datos quedarán dentro del contenedor)? [s/N] " resp
    if [[ ! "$resp" =~ ^[sS]$ ]]; then
        exit 1
    fi
fi

# ── 4. Construir imágenes Docker ─────────────────────────────────────────────
echo ""
echo "Construyendo imágenes Docker..."
docker compose build
echo "${OK} Imágenes construidas"

# ── 5. Migración de datos históricos (solo si la BD no existe) ───────────────
DB_PATH="$NFS_MOUNT/weights.db"
if mountpoint -q "$NFS_MOUNT" 2>/dev/null && [ ! -f "$DB_PATH" ]; then
    echo ""
    echo "Base de datos no encontrada. Ejecutando migración de CSVs históricos..."
    docker compose run --rm supurrmente python src/migrate.py
    echo "${OK} Migración completada"
elif [ -f "$DB_PATH" ]; then
    echo "${OK} Base de datos existente detectada — se omite la migración"
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
