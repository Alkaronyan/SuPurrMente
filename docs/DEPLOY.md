# Despliegue — SuPurrMente (Raspberry Pi)

Resumen: **clonar + `bash setup.sh`**. El script descifra `.env.age`, comprueba el NFS,
construye la imagen, migra si no hay BD y arranca el contenedor. Todos los **secretos
viajan cifrados** en `.env.age` (Gmail + OAuth de Google completo); solo necesitas la
passphrase de `age`. Lo único manual es infraestructura/datos y el login de Whisker.

## 0. Requisitos en la Pi (una vez)

`setup.sh` **instala solo lo que falte** del host (`age`, `docker`, `docker compose`) vía
apt — idempotente, y **nunca toca Python** (vive dentro del contenedor). Solo necesitas
poder usar `sudo`. Si Docker se instala por primera vez, añade tu usuario al grupo y
re-loguéate para no depender de `sudo` con docker:

```bash
sudo usermod -aG docker "$USER"   # solo si Docker se instaló ahora; re-loguea la sesión
```

## 1. Clonar y arrancar

```bash
git clone https://github.com/Alkaronyan/SuPurrMente.git
cd SuPurrMente
bash setup.sh                      # pedirá la passphrase de age para descifrar .env
```

`setup.sh` hace, en orden: descifra `.env.age` → `.env` (600) · verifica Docker · avisa si
el NFS no está montado · `docker compose build` · migra CSVs históricos **solo si** el NFS
está montado y no existe la BD · `docker compose up -d`.

## 2. Pasos manuales (no son secretos)

1. **Datos históricos.** `data/weights.db`/`.csv` y los CSV de `app/deprecated/` están
   *gitignored* (no vienen en el clone). Copia tu `weights.db` + `weights.csv` de dev al
   recurso **NFS del NAS** antes del primer arranque, o el sistema empezará con BD vacía y
   acumulará desde cero. (Alternativa: copiar los CSV a `app/deprecated/` y dejar que
   `setup.sh` los migre.)
2. **NFS** montado en `/etc/fstab` apuntando al NAS, p.ej.:
   ```
   <IP-NAS>:/volume1/cat-weights  /mnt/nas/cat-weights  nfs  defaults,_netdev  0  0
   ```
   (o acepta datos dentro del contenedor cuando `setup.sh` pregunte).
3. **NPM** (Nginx Proxy Manager): un **único forward** del dominio
   `supurrmente.gonzalez.team` → `<IP-de-la-Pi>:4180` (sin custom locations; oauth2-proxy
   reparte por ruta). ⚠️ Ver nota al final.
4. **Token de Whisker.** Tras el arranque, abre `https://supurrmente.gonzalez.team/whisker-login`
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

## Check one-time en Google (no se rellena nada)

El OAuth Client ya existe (sus credenciales están en `.env.age`). Solo confirma que tiene
autorizado el redirect `https://supurrmente.gonzalez.team/oauth2/callback`. Si lo
configuraste en dev con el dominio, está hecho.

---

> **Nota — NPM apunta al nodo correcto.** Durante el desarrollo, NPM apuntaba a la IP del
> **PC de dev**. Al pasar a producción hay que **reapuntar el proxy host de NPM a la IP de
> la Raspberry Pi** (puerto `4180`). Si se te olvida, el dominio seguirá sirviendo el nodo
> viejo (o dará error) aunque la Pi esté perfectamente arrancada.
