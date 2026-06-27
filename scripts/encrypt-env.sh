#!/bin/bash
# Cifra .env con age usando una contraseña maestra.
# Ejecuta esto una vez después de rellenar .env, antes del primer commit.
#
# Uso: bash scripts/encrypt-env.sh
set -e

if ! command -v age &>/dev/null; then
    echo "[ERROR] age no está instalado."
    echo "        En la Pi (Debian): sudo apt install age"
    echo "        En Mac:            brew install age"
    exit 1
fi

if [ ! -f .env ]; then
    echo "[ERROR] No se encontró .env en el directorio actual."
    exit 1
fi

age --passphrase .env > .env.age
echo ""
echo "[OK] .env.age creado. Ahora:"
echo "       git add .env.age"
echo "       git commit -m 'add encrypted credentials'"
echo ""
echo "Guarda la contraseña en tu gestor de contraseñas."
echo "La necesitarás cada vez que ejecutes setup.sh en hardware nuevo."
