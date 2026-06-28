#!/bin/bash
# deploy.sh — bootstrap de SuPurrMente en un solo paso.
#
# Crea la carpeta del repo con el DUEÑO correcto (tu usuario, no root), clona dentro
# y lanza setup.sh. Resuelve el problema típico de clonar con `sudo` en sitios de root
# (p.ej. /opt/stacks): si la carpeta es de root, setup.sh no puede escribir el .env.
#
# Uso (desde donde quieras el despliegue, p.ej. /opt/stacks):
#   curl -fsSLO https://raw.githubusercontent.com/Alkaronyan/SuPurrMente/main/deploy.sh
#   bash deploy.sh
#
# Funciona tanto si lo lanzas como tu usuario (usa sudo solo para mkdir/chown) como con
# `sudo bash deploy.sh` (clona y arranca como tu usuario humano, no como root).
set -euo pipefail

REPO="https://github.com/Alkaronyan/SuPurrMente.git"
DIR="SuPurrMente"

# Dueño del despliegue: el usuario humano (no root), aunque se invoque con sudo.
OWNER="${SUDO_USER:-$(id -un)}"

# sudo solo si no somos root.
SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi

# Ejecuta un comando COMO el dueño (baja de root si hiciera falta).
as_owner() {
    if [ "$(id -un)" = "$OWNER" ]; then
        "$@"
    else
        sudo -u "$OWNER" -- "$@"
    fi
}

echo "==> Despliegue en $(pwd)/$DIR  (dueño: $OWNER)"

# 1. Crear la carpeta (con sudo si el sitio es de root).
$SUDO mkdir -p "$DIR"

# 2. Cambiar la propiedad al usuario humano: que no quede nada de root.
$SUDO chown -R "$OWNER":"$OWNER" "$DIR"

# 3. Clonar (o actualizar) COMO el dueño, dentro de la carpeta ya suya.
if [ -d "$DIR/.git" ]; then
    echo "==> Repo ya presente; actualizando (git pull --ff-only)..."
    as_owner git -C "$DIR" pull --ff-only
else
    echo "==> Clonando $REPO ..."
    as_owner git clone "$REPO" "$DIR"
fi

# 4. Lanzar el setup (instala deps de host, descifra .env, construye y arranca).
echo "==> Lanzando setup.sh ..."
cd "$DIR"
as_owner bash setup.sh
