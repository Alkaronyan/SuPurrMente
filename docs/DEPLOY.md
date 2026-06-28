# Despliegue — SuPurrMente (Raspberry Pi)

Resumen: **clonar + `bash setup.sh`**. El script descifra `.env.age`, construye la imagen,
migra si no hay BD y arranca el contenedor. Todos los **secretos viajan cifrados** en
`.env.age` (Gmail + OAuth de Google + clave del backup); solo necesitas la passphrase de
`age`. Lo único manual es datos/red, el login de Whisker y (one-time) el receptor del NAS.

## 0. Requisitos en la Pi (una vez)

`setup.sh` **instala solo lo que falte** del host (`age`, `docker`, `docker compose`) vía
apt — idempotente, y **nunca toca Python** (vive dentro del contenedor). Solo necesitas
poder usar `sudo`. Si Docker se instala por primera vez, añade tu usuario al grupo y
re-loguéate para no depender de `sudo` con docker:

```bash
sudo usermod -aG docker "$USER"   # solo si Docker se instaló ahora; re-loguea la sesión
```

## 1. Clonar y arrancar

**Un solo comando** (recomendado). Desde donde quieras el despliegue (p.ej. `/opt/stacks`):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Alkaronyan/SuPurrMente/main/deploy.sh)
```

`deploy.sh` crea la carpeta con **tu** usuario como dueño (no root), clona dentro y lanza
`setup.sh`. Así evita el fallo típico de clonar con `sudo` en sitios de root (`/opt/stacks`):
si la carpeta es de root, `setup.sh` no podría escribir el `.env`. Sirve también para
**reparar** un clon ya hecho con `sudo` (corrige la propiedad y hace `git pull`).

Se usa `bash <(...)` (sustitución de proceso), **no `curl | bash`**: con la tubería, el
script ocuparía el stdin y se romperían los prompts (passphrase de age, sudo). Con
`bash <(...)` el terminal sigue siendo el stdin y todo funciona.

<details><summary>Alternativa manual</summary>

```bash
git clone https://github.com/Alkaronyan/SuPurrMente.git
cd SuPurrMente
bash setup.sh
```
Si el directorio acaba siendo de root, tendrás "Permission denied" al escribir `.env`.
</details>

`setup.sh` hace, en orden: instala deps de host que falten (`age`/Docker) · descifra
`.env.age` → `.env` (600) · prepara `./data` (local) · `docker compose build` · migra CSVs
históricos si no hay BD · `docker compose up -d`.

## 2. Pasos manuales (no son secretos)

1. **Datos.** `/data` es **local** (bind `./data`); SQLite no vive sobre NFS. `setup.sh`
   **restaura solo** del NAS si no hay BD local (con la clave **GLN1**, verbo `fetch`;
   necesita la **VPN al NAS** arriba). Idempotente: si ya hay BD local, no la toca (la local
   manda). Restaurar a mano si hiciera falta (la Pi NO tiene la clave de Alfred, va por GLN1):
   ```bash
   docker compose exec -u tracker supurrmente python src/restore.py
   ```
2. **NPM** (Nginx Proxy Manager): un **único forward** del dominio
   `supurrmente.gonzalez.team` → `<IP-de-la-Pi>:4180` (sin custom locations; oauth2-proxy
   reparte por ruta). ⚠️ Ver nota al final.
3. **Token de Whisker.** Tras el arranque, abre `https://supurrmente.gonzalez.team/whisker-login`
   (entra con Google `@gonzalez.team`) e introduce usuario+contraseña de Whisker **una vez**:
   se emite y guarda el token revocable; la contraseña no se almacena. Si no hay token, el
   sistema te manda un email con ese enlace.

## 3. Verificar

```bash
docker compose exec supurrmente supervisorctl status   # los 3 procesos en RUNNING
docker compose logs -f supurrmente                      # logs en vivo
curl -so /dev/null -w '%{http_code}\n' http://localhost:4180/   # dashboard → 200
```

- Dashboard (público): `https://supurrmente.gonzalez.team/`
- Explorador / SQL (login Google): `https://supurrmente.gonzalez.team/weights`

## Copia de seguridad al NAS

El job de backup (`backup.py`, cada `interval_days`) **empuja** una copia al NAS por SSH
(verbos `deposit`/`fetch` contra un receptor confinado; ni rsync ni NFS). La clave dedicada
viaja en `.env.age` → el entrypoint la deja en `/run/secrets/backup_ssh_key` (600,
`tracker`). Por deploy solo hay que asegurar que **la Pi alcanza el NAS** (si va por VPN,
la VPN del host levantada; el contenedor sale por el enrutado del host).

**Setup del NAS (one-time, ya hecho; aquí para reproducir o en otro NAS):**

1. En `~GLN1/.ssh/authorized_keys`, la pública de la clave dedicada con forced-command:
   ```
   command="/var/services/homes/GLN1/backup-only.sh",restrict ssh-ed25519 AAAA… gln1-backup
   ```
   Perms estrictos (Synology `StrictModes`): home `700`, `.ssh` `700`, `authorized_keys` `600`,
   todo propiedad de `GLN1`, y **cada clave en su línea**.
2. El receptor `~GLN1/backup-only.sh` (`700`): `cat`→`.part`→`mv` atómico, confinado por
   `basename` a `/volume1/backups/SuPurrMente_data` (verbos deposit/fetch/list/remove-history).
3. **ACL** (GLN1 está vetado en el share `backups` por política de nodos): darle a GLN1
   **solo Atravesar** en `backups` (editando su `deny` para que no incluya travesía) y
   **Lectura/Escritura** en `SuPurrMente_data`. Así escribe su subcarpeta sin ver el resto.

Restaurar = copiar `weights.db`/`.csv` de `…/SuPurrMente_data/` a `./data` (paso 1 de arriba).
Las copias datadas para volver atrás están en `…/SuPurrMente_data/history/`.

## Check one-time en Google (no se rellena nada)

El OAuth Client ya existe (sus credenciales están en `.env.age`). Solo confirma que tiene
autorizado el redirect `https://supurrmente.gonzalez.team/oauth2/callback`. Si lo
configuraste en dev con el dominio, está hecho.

---

> **Nota — NPM apunta al nodo correcto.** Durante el desarrollo, NPM apuntaba a la IP del
> **PC de dev**. Al pasar a producción hay que **reapuntar el proxy host de NPM a la IP de
> la Raspberry Pi** (puerto `4180`). Si se te olvida, el dominio seguirá sirviendo el nodo
> viejo (o dará error) aunque la Pi esté perfectamente arrancada.
