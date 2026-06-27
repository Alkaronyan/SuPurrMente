# Sesión 2026-06-27 — Login con Google y dashboard público

Tras la V1, el servicio web exponía **toda la base de datos sin autenticación**:
Datasette servía en `/` su explorador por defecto (todas las tablas, navegación de
filas) y `/weights.json?sql=` ejecutaba **SQL arbitrario** — cualquiera con acceso
podía sacar el serial del robot, `api_meta`, alertas, todo. Esta sesión cierra eso.

## Objetivo (del usuario)

- Botón de **iniciar sesión solo con cuentas de Google**, y solo aceptar cuentas del
  dominio **@gonzalez.team**.
- Lo que hoy está en la BD → visible **solo con login**, y en **otra URL** (no la base).
- En la **URL base** → el **dashboard**, visible **sin** login.

## Decisiones

- **Mecanismo:** `oauth2-proxy` detrás de NPM (Nginx Proxy Manager, que ya corre en la
  Pi y hace el SSL). Se descartó el plugin de Datasette (no hay plugin mantenido de
  Google Workspace; habría que escribir y mantener el OAuth a mano) y Authentik/Authelia
  (un IdP completo es excesivo para esto).
- **Qué es público:** los gráficos de peso. Lo que se protege es el **acceso crudo/SQL**
  a la base (explorador completo).

## Arquitectura

Un solo dominio en NPM, enrutado por path:

```
NPM (SSL) ── /        → datasette-public    (gráficos, sin login)
          ── /db/     → oauth2-proxy → datasette-private  (BD + SQL, login @gonzalez.team)
          ── /oauth2/ → oauth2-proxy        (callback de Google)
```

**Dos instancias de Datasette sobre la misma BD (solo lectura):**

- `datasette-public` (`datasette.public.yml`): `/` sirve el dashboard vía el plugin
  `plugins/homepage.py` (sirve `dashboard.html` en la raíz, sin redirect, manteniendo
  la URL). **`allow_sql: false`** (no SQL libre) y **`allow: false` por tabla** (no
  navegación). Expone solo 3 *canned queries* parametrizadas: `cat_daily`, `box_daily`,
  `robot_status`. Publica el puerto 8001; NPM lo proxea en la raíz.
- `datasette-private` (`datasette.yml`, `--setting base_url /db/`): Datasette completo.
  **Sin puerto publicado**: solo alcanzable por oauth2-proxy. El control de acceso lo
  hace el proxy.
- `oauth2-proxy` (imagen `quay.io/oauth2-proxy/oauth2-proxy:v7.6.0`): provider `google`,
  `--email-domains=gonzalez.team`, `--reverse-proxy` (lee `X-Forwarded-*` de NPM),
  `--cookie-secure`. Upstream = `datasette-private`. Perfil compose `auth` → solo arranca
  en producción (`COMPOSE_PROFILES=auth` en `.env`); en dev solo corre el dashboard
  público.

El **botón de login**: oauth2-proxy ya muestra "Sign in with Google"; además el
dashboard público tiene un botón **"🔒 Iniciar sesión"** que enlaza a `/db/`.

## Cambios en el dashboard

El dashboard dejó de construir SQL en el cliente (`/weights.json?sql=...`) y ahora llama
a las canned queries (`/weights/cat_daily.json?cat=…&start=…&end=…`). Las queries usan
`(:start = '' OR date(timestamp) >= :start)` para que "toda la historia" (params vacíos)
funcione sin filtro. Cero cambios en la lógica de Chart.js.

## Por qué dos instancias y no una

Datasette cascada de permisos: bloquear tablas a nivel de base también bloquea las
canned queries. Mantener "público con canned queries" y "privado con todo" en un solo
proceso es frágil. Dos instancias Datasette leyendo el mismo SQLite (lectores
concurrentes, sin problema) es más simple y robusto, y deja el control de acceso del
lado privado enteramente en oauth2-proxy.

## Verificación

- `make build` (tracker + datasette-public) y **116 tests verdes** en contenedor.
- `test_e2e.py` reescrito: arranca **las dos** instancias. Pública: `/` sirve el
  dashboard, `?sql=` → **403**, `/weights/<tabla>.json` → **403** (visits, robot_snapshots,
  api_meta, sent_alerts), canned queries → 200. Privada: tablas + SQL → 200.
- Humo real contra la BD de dev: `/` renderiza los gráficos de ambos gatos, el botón de
  login apunta a `/db/`, las canned queries devuelven datos, SQL y tablas dan 403
  (verificado por captura headless).

## Afinado de UX (tras la primera prueba en prod)

- **Plugins separados por instancia**: `plugins/public/homepage.py` (dashboard + favicon
  en `/`) y `plugins/private/logout.py` (botón "Cerrar sesión" + favicon). Cada Datasette
  carga el suyo con `--plugins-dir /app/plugins/{public,private}`.
- **Sin página intermedia**: `OAUTH2_PROXY_SKIP_PROVIDER_BUTTON=true` → pulsar el botón
  del dashboard va directo a Google (antes paraba en la página propia de oauth2-proxy).
- **Botón estándar de Google**: el del dashboard es ahora el oficial "Iniciar sesión con
  Google" (SVG del logo de 4 colores + branding), no un genérico.
- **Cerrar sesión**: botón fijo inyectado en el explorador → `/oauth2/sign_out?rd=/`.
- **Favicon**: `static/favicon.ico`, enlazado en `dashboard.html` y servido por ambos
  plugins en `/favicon.ico`.

### Tropezones de NPM (single-host por path)

- `/db/` daba **404 "Database not found"** de Datasette: la petición llegaba a
  `datasette-public` (que no tiene una base "db"). Causa: faltaba/estaba mal la *custom
  location* en NPM. Hay que enrutar **`/db` y `/oauth2`** → `oauth2-proxy:4180`; el resto
  (`/`) → `datasette-public:8001`. Sin reescritura de path (el base_url `/db/` y oauth2-proxy
  necesitan la ruta tal cual).
- El **cookie secret** de `openssl rand -base64 32` (44 chars) hace *crashear* a
  oauth2-proxy: quiere 16/24/32 **bytes**. Solución: 24 bytes aleatorios → base64 = 32
  chars exactos.

## Pendiente al desplegar (no es código)

1. **Google Cloud:** OAuth Client (consent screen *Internal* en el Workspace gonzalez.team
   = doble candado), redirect `https://<dominio>/oauth2/callback`.
2. **`.env`:** `OAUTH2_PROXY_CLIENT_ID/SECRET/COOKIE_SECRET/REDIRECT_URL` + `COMPOSE_PROFILES=auth`.
   `COOKIE_SECRET` = `openssl rand -base64 32`. Reencriptar `.env.age`.
3. **NPM:** sobre el proxy host del dominio, *custom locations* `/db` y `/oauth2` →
   `http://<pi>:4180` (oauth2-proxy); la raíz `/` → `http://<pi>:8001` (datasette-public).
