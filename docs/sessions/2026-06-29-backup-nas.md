# 2026-06-29 — Copia de seguridad al NAS (push por SSH)

Se añadió un sistema de backup del estado al NAS. Decisión de fondo: **el dato vivo es
LOCAL** (bind `/data` en el host; SQLite sobre NFS se corrompe) y el NAS es solo **destino
de copia** al que el contenedor **empuja**. Antes los docs asumían `/data` = NFS del NAS;
eso se corrigió (`docker-compose.yml`, `setup.sh`, ARCHITECTURE/CLAUDE).

## Diseño (decidido con el usuario)

- **Cada 4 días** (`interval_days`), con **reintento al día siguiente** si falla.
- **Contrato de consistencia** antes de publicar: se baja el backup anterior (`fetch`) y se
  exige que el snapshot sea **superconjunto** del backup (cada fila previa sigue presente),
  conteos que no decrecen y `max(timestamp)` que no retrocede. Clave: **no** es un check de
  fechas — el backfill de CSV añade fechas viejas legítimamente; lo que se vigila es no
  PERDER filas. `integrity_check` en ambos lados.
- **Atómico + rollback**: snapshot con `VACUUM INTO`; publicación `.part`→`mv`; copias
  datadas en `history/` rotadas a `retention`; `manifest.json` (conteos + sha256) como
  prueba forense y referencia.
- **En fallo**: no se publica → cuarentena local + `report.json` para forense + **email
  crítico**. Un corte de red nunca pisa la última copia buena (verifica antes + rename
  atómico). Se distingue fallo transitorio (reintento) de fallo de consistencia (forense).
- Módulo `backup.py` (lógica pura testeable: `snapshot`, `check_consistency`,
  `build_manifest`; transferencia aparte). Job en `webapp.py`. Config en `config.yml`
  (`backup:`). 8 tests (`test_backup.py`), incl. el caso estrella: **el backfill de fechas
  viejas debe pasar**. Suite total **159 verde**.

## El transporte: por qué NO rsync ni SFTP, sí SSH-exec

Primer intento con **rsync-sobre-SSH** → Synology lo capa: su binario responde
`service disabled`/`rsync service is no running` aunque el daemon (873) esté arriba. rsync
**no es pasivo** (arranca un `rsync --server` en el NAS), y Synology lo gobierna con toggles
caprichosos. **SFTP** tampoco: Synology lo **enjaula al home**, no llega a `/volume1`.

Solución: **SSH-exec con verbos** contra un receptor mínimo `backup-only.sh`
(`cat`→`.part`→`mv`, confinado por `basename`). El NAS solo ejecuta `cat`/`mv` — pasivo de
verdad, atómico, inmune a los servicios de Synology, y **confinado aunque GLN1 sea admin**.
Se quitó `rsync` de la imagen; basta `openssh-client`.

## Autenticación GLN1: la saga de Synology (lecciones)

Clave **dedicada** ed25519 (no la maestra de Alfred), identidad **GLN1**, forced-command que
solo permite los verbos. La privada va en `.env` (base64 `BACKUP_SSH_KEY_B64`) → el
entrypoint la decodifica a `/run/secrets/backup_ssh_key` (600, `tracker`; nunca `oauth`).

Gotchas resueltos (todos de Synology):
1. **`PasswordAuthentication no`** en el NAS → solo claves; la instalación de la clave se
   hace como GLN1 con su clave o vía admin.
2. **Claves pegadas**: un `cat >>` sin salto de línea final fusionó dos entradas de
   `authorized_keys` en una → ninguna válida. Cada clave en su línea.
3. **`StrictModes`**: el home en `777` hacía que sshd ignorara la clave. Home `700`, `.ssh`
   `700`, `authorized_keys` `600`, todo de `GLN1`.
4. **ACL de Synology**: el share `backups` **deniega explícitamente a los nodos GLN0–4** (y
   `amigos`), y el `deny` por usuario **gana** al `allow` de grupo `administrators` (GLN1 es
   admin pero estaba vetado). En el filesystem (SSH/shell) la ACL **sí** se aplica (a
   diferencia de SMB/File Station, donde los admin se la saltan — de ahí la advertencia de
   DSM, que es irrelevante para SSH). Solución de mínimo privilegio: a GLN1, **solo
   Atravesar** en `backups` (editando su `deny` para que no incluya travesía; un `allow`
   suelto no basta porque deny>allow) + **RW** en `SuPurrMente_data`. Así pasa por `backups`
   sin verlo y escribe solo su carpeta.

## Verificación

Probado end-to-end contra el NAS real (dev): dos pasadas `ok: true`, ficheros en el NAS
**propiedad de GLN1** (`weights.db` compactado por VACUUM, `weights.csv`, `manifest.json`,
`history/` con copias datadas), y la 2ª pasada ejerció el `fetch` + contrato de
consistencia. Setup del NAS documentado en `docs/DEPLOY.md`.

## Restauración (seed del deploy) y despliegue en la Pi

`restore.py` + `backup.restore_if_missing`: en un despliegue nuevo, si la BD local **falta
o está vacía** (`ensure_db` crea una vacía al arrancar), la trae del NAS con el verbo
`fetch` (clave GLN1). **Idempotente**: si la local ya tiene datos, no la toca — la local es
la fuente de verdad (el backup nunca es más fresco), así que no hay que "comparar" nada.
`setup.sh` lo llama siempre (decide `restore.py` por nº de filas, no por existencia del
fichero). En modo comando la clave se saca del `.env` montado; en `exec`, de `/run/secrets`.

Desplegado en `glnode1` (Pi) con `bash <(curl … deploy.sh)`: deps + descifrado + build +
**restore del NAS** (`{'restored': '/data/weights.db'}`) + arranque. Los 3 procesos RUNNING,
dashboard servido por HTTPS (NPM → oauth2-proxy → Google, autenticado), scheduler con los 3
jobs (fetch 6h, refresco 15 min, backup 4 días). Login de Whisker → ciclo inmediato OK.

Correcciones de despliegue de esta tanda: `migrate.py` no peta si no existe `deprecated/`;
`/data` es **bind local** (no NFS) en compose/setup; deploy en **un comando** con
`bash <(curl …)` (no `curl | bash`, que rompe los prompts de age/sudo); el resumen de
`setup.sh` ya no hardcodea URL/puerto (URL del redirect de OAuth, puerto del mapeo de Docker).

## Lección: el backup va por LAN, no por VPN

Estuve arrastrando un "VPN al NAS arriba" de un comentario inicial sin verificarlo. Medido en
la Pi: `alabama.gonzalez.team` → `192.168.0.250` (misma subred), ruta `dev eth0` → **LAN
directa**. Hay interfaces VPN (`wg0`/`tun0`/`tun1`) pero el tráfico al NAS no las toca.

## Lección: hueco de datos del 26–28 jun = fallo del robot, no nuestro

Dos días sin datos — **también en la app oficial de Whisker**. Eso prueba que el fallo fue
del **LR4 → nube de Whisker** (conectividad/firmware del robot colgada), no de nuestro
sistema (que está aguas abajo y no puede afectar a la app oficial). El corte fue el 26-jun,
**antes** de tocar las conexiones del NAS (28-jun): lo descubrimos, no lo causamos. Un
apagado/encendido del robot lo arregló. En producción, la **alerta de ausencia** (24h) y los
`robot_snapshots`/`is_online` cazarían esto con un email — durante el hueco el sistema aún no
corría en prod, por eso no saltó.
