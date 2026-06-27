# Sesión 2026-06-28 — Un contenedor, token de Whisker y aislamiento de credenciales

Reescritura del empaquetado y de la autenticación, manteniendo intacta la lógica de
datos. De **4 contenedores** a **uno** (decisión del usuario: uso personal), pero con el
endurecimiento que de verdad importa: **las credenciales sensibles aisladas por usuario**
y **Whisker por token revocable, sin contraseña en disco**.

## Decisiones (y por qué)

- **Un contenedor** con `supervisord` (PID por `tini`) y **tres usuarios de sistema**.
  La frontera de seguridad pasa de "un contenedor por proceso" a "un UID por proceso".
  El usuario aceptó perder la BD cruda como secreto (es el peso de dos gatos); lo que NO
  se negocia son las credenciales.
- **Aislamiento de credenciales por UID + ficheros 600.** El entrypoint reparte el `.env`
  (montado como fichero, **no** inyectado como entorno global) en `/run/secrets/{tracker,oauth}.env`,
  cada uno 600 de su usuario. `/run/secrets` es 711 (atravesable, no listable). Verificado:
  como `oauth` (el proceso de cara a internet), `cat /run/secrets/tracker.env` → *Permission denied*.
  Un oauth2-proxy comprometido no llega ni a Gmail ni al token de Whisker.
- **Whisker por token.** `pylitterbot` soporta `Account(token=…, token_update_callback=…)`.
  La contraseña solo se usa una vez en un **formulario web** para emitir el token; se
  descarta. El token (revocable) se guarda en `/data/whisker_token.json` (600, solo `tracker`).

## Arquitectura resultante

```
NPM (SSL) ── todo ──▶ oauth2-proxy :4180 (usuario 'oauth')
   público:  /  /static  /favicon.ico  /weights/*_daily.json + robot_status.json   → datasette
   login:    /whisker-login → tracker(:8082) · /weights, SQL, /-/ → datasette(:8081)
```

- `oauth2-proxy` (usuario `oauth`): única puerta, único puerto. `skip_auth_routes` =
  allow-list de rutas públicas; `skip_provider_button` → directo a Google.
- `datasette` (usuario `datasette`): una sola instancia **full**, escucha en `127.0.0.1`.
  El candado público/privado lo pone el proxy, no Datasette. Lee la BD por el grupo `data`
  (640); el token (600) no lo ve.
- `tracker` (usuario `tracker`): uvicorn con el formulario `/whisker-login` + **APScheduler**
  (ciclo de datos 6h + refresco del token). Sustituye al cron. Posee el token y el secreto de Gmail.

## Flujo de Whisker

1. Sin token → `run_pipeline` lanza `WhiskerAuthRequired` → email (cooldown 24h) con el
   enlace a `/whisker-login`.
2. El formulario va tras oauth2-proxy (solo `@gonzalez.team`). CSRF double-submit, no
   loguea el password. `login_and_store` → guarda el token, arranca un ciclo inmediato.
3. El fetcher usa el token; un job lo refresca al pasar la **media vida** del access token
   (se decodifica el `exp` del JWT). El refresh token rotado se persiste por callback.

## El candado ahora es config del proxy → test que lo vigila

Al unificar Datasette (full), se pierde la "doble red" del `allow_sql:false`. La
protección pública/privada vive en `oauth2-proxy.cfg` (`skip_auth_routes`).
`tests/test_oauth_routes.py` parsea esa allow-list y verifica que las rutas públicas
estén y las sensibles (tablas, SQL, `/weights`, `/-/`, `/whisker-login`) NO — la red de
seguridad ante un aflojamiento del límite.

## Tropezones resueltos

- **Cookie secret**: `openssl rand -base64 32` (44 chars) rompe oauth2-proxy (quiere
  16/24/32 **bytes**). Solución: 24 bytes aleatorios → base64 = 32 chars exactos.
- **`/run/secrets` 700**: los usuarios no podían atravesar el directorio para leer su
  propio fichero. Fix: 711.
- **App-password de Gmail con espacios**: `source`-ar el fichero lo evaluaba como shell
  (`jaxy: command not found`, exit 127). Fix: `export "$line"` por línea (sin evaluación).
- **Datasette no arranca sin BD**: `ensure_db.py` crea el esquema en el entrypoint (como
  `tracker`) antes de levantar los servicios.
- **`[.]` en los regex de skip_auth** rompía el parser naïf del test (el `]` interno
  cerraba el match) → parser línea a línea.

## Estado al cierre

- **143 tests** verdes en el contenedor (nuevos: `test_whisker_auth`, `test_webapp`,
  `test_oauth_routes`; `test_e2e` reescrito a instancia única).
- Smoke en vivo: 3 procesos `RUNNING`; rutas públicas 200, privadas → Google; aislamiento
  de secretos verificado; dashboard renderiza vía `:4180`.
- **Pendiente de despliegue**: en NPM, dejar **un único forward** del dominio → `:4180`
  (quitar las custom locations `/db` y `/oauth2`). El redirect de Google no cambia.
- Nada commiteado aún.
