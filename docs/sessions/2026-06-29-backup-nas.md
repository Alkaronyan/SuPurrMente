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
