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

# ── 1. Verificar/descifrar .env ──────────────────────────────────────────────
if [ ! -f .env ]; then
    if [ -f .env.age ]; then
        if ! command -v age &>/dev/null; then
            echo "${ERR} Se encontró .env.age pero 'age' no está instalado."
            echo "      En Debian/Raspi: sudo apt install age"
            exit 1
        fi
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

# ── 2. Verificar dependencias ────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo -e "${ERR} Docker no está instalado. Instálalo primero."
    exit 1
fi
if ! docker compose version &>/dev/null; then
    echo -e "${ERR} Docker Compose (v2) no está disponible."
    exit 1
fi
echo "${OK} Docker y Docker Compose disponibles"

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
