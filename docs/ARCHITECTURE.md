# Arquitectura — SuPurrMente

Estado real del sistema. Para el *porqué* de las decisiones, ver
[CONTEXT.md](CONTEXT.md) y los [logs de sesión](sessions/).

## Un contenedor, tres procesos, tres usuarios

Todo corre en **un solo contenedor** (`supurrmente`). Dentro, `supervisord` (PID
gestionado por `tini`) lanza tres procesos, **cada uno con su usuario de sistema**:

| Proceso | Usuario | Escucha | Cometido |
|---|---|---|---|
| `oauth2-proxy` | `oauth` | **0.0.0.0:4180** (único puerto publicado) | Login Google + reparto por ruta |
| `datasette` | `datasette` | `127.0.0.1:8081` | Dashboard + explorador de la BD |
| `tracker` (uvicorn) | `tracker` | `127.0.0.1:8082` | Formulario `/whisker-login` + scheduler |

NPM (en la Pi) termina el SSL y manda **todo** a `:4180`. oauth2-proxy es la única
puerta: reparte por ruta y decide qué es público y qué exige login.

```
NPM (SSL, supurrmente.gonzalez.team) ── todo ──▶ oauth2-proxy :4180
        público (sin login):  /  ·  /static  ·  /favicon.ico  ·  /weights/*_daily.json + robot_status.json
        login @gonzalez.team:  /whisker-login (→tracker)  ·  /weights, SQL, /-/ (→datasette)
```

## Aislamiento de credenciales (la razón de los tres usuarios)

Los secretos se reparten en ficheros **600, cada uno propiedad del proceso que lo
usa** (el entrypoint los extrae del `.env` montado; **no** se inyectan como entorno
global). `/run/secrets` es `711` (atravesable, no listable).

- `oauth` (el único de cara a internet) solo lee `oauth.env` (Google client/secret,
  cookie). **No puede leer** los secretos del tracker (Linux deniega `/proc` y ficheros
  600 de otro UID). No tiene acceso a `/data`.
- `tracker` lee `tracker.env` (Gmail) y posee el **token de Whisker** (`/data/whisker_token.json`,
  600). Un oauth2-proxy comprometido **no llega** a Gmail ni al token.
- `datasette` no tiene secretos; lee la BD por el grupo `data` (la BD es 640 grupo
  `data`; el token, 600, queda fuera de su alcance).

Verificado: como `oauth`, `cat /run/secrets/tracker.env` → *Permission denied*.

## Autenticación con Whisker: por token, sin contraseña

La contraseña de Whisker **no se guarda en ningún sitio**. Flujo:

1. Sin token válido, el ciclo lanza `WhiskerAuthRequired` → email (cooldown 24h) con el
   enlace a **`/whisker-login`**.
2. Ese formulario está tras oauth2-proxy → solo entra una cuenta `@gonzalez.team`.
   Pides usuario+contraseña, `pylitterbot` hace login **una vez**, se extrae el token
   y se guarda (600). El password se usa y se descarta (no se loguea).
3. A partir de ahí, el fetcher usa el **token** (`Account(token=…, token_update_callback=…)`).
4. Un job refresca el token al pasar la **media vida** del access token (JWT `exp`),
   persistiendo el rotado. El token es **revocable** (cambiar la contraseña en Whisker
   lo invalida) y acotado a esta app.

Módulo: `whisker_auth.py`. Formulario + scheduler: `webapp.py`.

## Flujo de datos (cada ciclo del scheduler)

```
fetcher(token) → [api_contract + version log] → classifier (validación) → crosscheck (tendencia) →
SQLiteStore + CsvStore → HealthChecker + robot_health → EmailSender
```

El **scheduler** (APScheduler, dentro de `webapp.py`) sustituye al cron: ciclo de datos
cada 6h + refresco de token. La idempotencia se mantiene (mismas garantías: `INSERT OR
IGNORE`, dedup CSV, cooldown de alertas).

## Módulos (`app/src/`)

| Módulo | Rol |
|---|---|
| `webapp.py` | uvicorn: formulario `/whisker-login` + APScheduler (fetch 6h, refresco token) |
| `whisker_auth.py` | Token de Whisker: guardar/cargar (600), login, refresco a media vida |
| `main.py` | `run_pipeline`: orquesta un ciclo; si no hay token, email con el enlace |
| `fetcher.py` | API → `FetchResult` (visitas + contrato + versiones + datos del robot) |
| `api_contract.py` | Valida que la API sigue dando lo esperado |
| `classifier.py` | Umbral dinámico; `classify_known` valida el gato de la API |
| `crosscheck.py` | Robustez secundaria: regresión de la tendencia reciente por gato; si el peso no encaja con el gato que dice la API, manda un email (no reasigna — la API manda) |
| `timeutils.py` | Única fuente de verdad de zona horaria (Europe/Madrid) |
| `storage/sqlite_store.py` | Primario; `visits`, `sent_alerts`, `api_meta`, `box_usage`, `robot_snapshots` |
| `storage/csv_store.py` | CSV de respaldo en `/data` (local), versionado por API |
| `backup.py` | Copia al NAS por SSH (snapshot consistente + contrato + publicación atómica) |
| `alerts/*` | Salud por gato, estado del robot, email |
| `migrate.py` | Una vez: ingiere `deprecated/*.csv` → SQLite + CSV |
| `ensure_db.py` | Crea el esquema SQLite al arrancar (Datasette no levanta sin BD) |
| `plugins/homepage.py` | Sirve el dashboard en `/` y el favicon |
| `plugins/logout.py` | Botón "Cerrar sesión" en el explorador (→ `/oauth2/sign_out`) |

## El límite público/privado vive en oauth2-proxy

Como hay **una sola Datasette de acceso completo**, el candado lo pone el proxy
(`oauth2-proxy.cfg`, `skip_auth_routes`): allow-list estricta de rutas públicas; todo
lo demás exige login. `tests/test_oauth_routes.py` verifica que no se afloje. (Se
acepta perder la "doble red" del `allow_sql:false` — la BD cruda no es sensible aquí;
los secretos sí, y esos los protege el aislamiento por usuario.)

## Backup al NAS (push por SSH, no NFS)

**El dato vivo es LOCAL**: `/data` es un bind del host (SQLite no debe vivir sobre NFS —
se corrompe). El NAS es solo **destino de copia**, y el contenedor **empuja** (no monta).

`backup.py` corre como job programado (cada `interval_days`, ver `webapp.py`) y, en cada
copia: **(1)** snapshot consistente en caliente (`VACUUM INTO` + `integrity_check`);
**(2)** baja el backup anterior del NAS y valida el **contrato de consistencia** —
superconjunto por identidad (backup ⊆ snapshot), conteos que no decrecen, `max(ts)` que no
retrocede (el backfill de fechas viejas es legítimo, no se penaliza); **(3)** si pasa,
**publica atómico** (`.part` → `mv` en el NAS) `weights.db`/`.csv`, una copia datada en
`history/` (rotada a `retention`) y `manifest.json`; **(4)** si falla, **no publica**:
cuarentena local + `report.json` para forense, y email crítico. Un corte de red nunca pisa
la última copia buena (verificación previa + rename atómico).

Transporte: **SSH-exec con verbos `deposit`/`fetch`** contra un receptor confinado en el
NAS (`backup-only.sh`: `cat`→`.part`→`mv`, acotado por `basename`). Ni rsync ni SFTP — el
NAS solo hace `cat`/`mv`. Clave **dedicada** de mínimo privilegio (identidad GLN1,
forced-command), en `.env` cifrada → fichero 600 de `tracker`. Setup en `docs/DEPLOY.md`.

El CSV local (`/data/weights.csv`) sigue siendo auto-descriptivo y versionado por API
(cabecera `# api_version:`, rota al cambiar la versión de Whisker). Ver `csv_store.py`.

## Configuración

`app/config.yml`: semillas, ventanas de salud, `crosscheck` (ventana de tendencia,
margen, MAD), `schedule.fetch_cron` (6h) y `refresh_fraction` (0.5),
`whisker.token_path` / `login_url`, rutas de almacenamiento.
Los emails y secretos se leen del `.env` (repartido en ficheros 600), **no** de `config.yml`.

## Despliegue

Imagen multi-arch (amd64 dev / arm64 Pi); el binario de oauth2-proxy se copia de su
imagen oficial. `setup.sh` descifra `.env.age`, comprueba el NFS, construye y arranca.
**NPM: un único forward del dominio → `<pi>:4180`** (sin custom locations).

## Fuera de alcance

Home Assistant, Grafana, despliegue cloud, push en tiempo real (`robot.subscribe()`
existe pero el polling 6h basta), y la atomización en varios contenedores (uso personal:
se prioriza un contenedor con aislamiento por usuario sobre la separación por contenedor).
