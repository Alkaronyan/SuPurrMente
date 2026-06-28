"""
Servicio web del tracker (corre como el usuario `tracker`).

Dos cometidos:
1. Sirve **/whisker-login** — el formulario que pide usuario+contraseña de Whisker
   UNA vez, emite el token y lo guarda (600). El password no se almacena ni se loguea.
   Va detrás de oauth2-proxy, así que solo lo alcanza una cuenta @gonzalez.team.
2. Programa con APScheduler el **ciclo de datos** (cada 6h) y el **refresco del token**
   (al pasar la media vida del access token).

Lo arranca uvicorn: ``uvicorn webapp:app --host 127.0.0.1 --port 8082`` (1 worker).
"""
import asyncio
import logging
import os
import secrets
import sys
from contextlib import asynccontextmanager
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pylitterbot.exceptions import LitterRobotLoginException
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, PlainTextResponse
from starlette.routing import Route

import backup
import timeutils
import whisker_auth
from main import load_config, run_pipeline

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("webapp")

config = load_config()

CSRF_COOKIE = "wl_csrf"
# En producción la cookie va por HTTPS (NPM); en local/test se desactiva con env.
COOKIE_SECURE = os.environ.get("WL_COOKIE_SECURE", "true").lower() != "false"

_STYLE = """
  *,*::before,*::after{box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
       background:#f5f5f5;color:#333;margin:0;min-height:100vh;
       display:flex;align-items:center;justify-content:center;padding:1.5rem}
  .card{background:#fff;border-radius:8px;box-shadow:0 1px 6px rgba(0,0,0,.1);
        padding:1.75rem;max-width:380px;width:100%}
  h1{font-size:1.25rem;margin:0 0 .25rem}
  p.sub{margin:0 0 1.25rem;color:#777;font-size:.85rem}
  label{display:block;font-size:.8rem;color:#555;margin:.75rem 0 .25rem}
  input{width:100%;padding:.55rem .6rem;border:1px solid #ccc;border-radius:4px;font-size:.95rem}
  button{margin-top:1.25rem;width:100%;padding:.6rem;border:0;border-radius:4px;
         background:#4285F4;color:#fff;font-size:.95rem;font-weight:600;cursor:pointer}
  button:hover{background:#3071e8}
  .msg{margin:.75rem 0 0;padding:.6rem .7rem;border-radius:4px;font-size:.85rem}
  .msg.err{background:#fdecea;color:#b3261e}
  .msg.ok{background:#e6f4ea;color:#1e8e3e}
  a{color:#4285F4}
"""


def _page(body: str, status: int = 200) -> HTMLResponse:
    html = (f'<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>SuPurrMente — Iniciar sesión en Whisker</title>'
            f'<link rel="icon" href="/static/favicon.ico">'
            f'<style>{_STYLE}</style></head><body>{body}</body></html>')
    return HTMLResponse(html, status_code=status)


def _form(csrf: str, message: str = "", kind: str = "") -> str:
    note = f'<div class="msg {kind}">{message}</div>' if message else ""
    return f"""
    <form class="card" method="POST" action="/whisker-login" autocomplete="off">
      <h1>🐾 Conectar con Whisker</h1>
      <p class="sub">Introduce tus credenciales de la app de la Litter-Robot. Se usan
      una sola vez para emitir un token; <strong>no se guardan</strong>.</p>
      <input type="hidden" name="csrf" value="{csrf}">
      <label for="u">Usuario (email)</label>
      <input id="u" name="username" type="email" required autofocus>
      <label for="p">Contraseña</label>
      <input id="p" name="password" type="password" required>
      <button type="submit">Iniciar sesión</button>
      {note}
    </form>"""


def _csrf_response(body: str, status: int = 200) -> HTMLResponse:
    """Renderiza una página con un token CSRF nuevo y lo fija como cookie (double-submit)."""
    csrf = secrets.token_urlsafe(32)
    resp = _page(body.replace("__CSRF__", csrf), status=status)
    resp.set_cookie(CSRF_COOKIE, csrf, max_age=900, httponly=True,
                    secure=COOKIE_SECURE, samesite="lax", path="/whisker-login")
    return resp


async def login_form(request):
    return _csrf_response(_form("__CSRF__"))


async def login_submit(request):
    form = await request.form()
    # CSRF double-submit: el campo del formulario debe coincidir con la cookie.
    cookie = request.cookies.get(CSRF_COOKIE, "")
    if not cookie or not secrets.compare_digest(form.get("csrf", ""), cookie):
        return _csrf_response(
            _form("__CSRF__", "La sesión del formulario caducó. Reinténtalo.", "err"),
            status=400)

    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    if not username or not password:
        return _csrf_response(
            _form("__CSRF__", "Rellena usuario y contraseña.", "err"), status=400)

    try:
        await whisker_auth.login_and_store(config, username, password)
    except LitterRobotLoginException:
        # No logueamos el password ni el detalle: solo que falló la autenticación.
        log.warning("Login de Whisker rechazado para %s", username)
        return _csrf_response(
            _form("__CSRF__", "Usuario o contraseña incorrectos.", "err"), status=401)
    except Exception:
        log.exception("Login de Whisker falló por error inesperado")
        return _csrf_response(
            _form("__CSRF__", "Error al conectar con Whisker. Inténtalo más tarde.", "err"),
            status=502)

    log.info("Token de Whisker emitido y guardado (usuario %s)", username)
    # Arranca un ciclo inmediato para que los datos empiecen a fluir ya.
    if _scheduler.running:
        _scheduler.add_job(_fetch_job, id="fetch-now", replace_existing=True)
    return _page(
        '<div class="card"><h1>✅ Conectado con Whisker</h1>'
        '<p class="sub">Token guardado. La recogida de datos se ha reactivado.</p>'
        '<p><a href="/">← Volver al dashboard</a></p></div>')


async def healthz(request):
    return PlainTextResponse("ok")


# ── Tareas programadas ────────────────────────────────────────────────────────
_scheduler = AsyncIOScheduler(timezone=timeutils.LOCAL_TZ)


async def _fetch_job():
    log.info("Ciclo de datos (programado)")
    await run_pipeline(config)


def _alert_backup_failure(error) -> None:
    """Email crítico de backup fallido (con cooldown). Importes locales para no acoplar
    el arranque del scheduler al stack de alertas."""
    from alerts.health import Alert
    from main import _send_with_cooldown
    from storage.sqlite_store import SQLiteStore
    alert = Alert(cat="sistema", severity="critical", kind="backup_failed",
                  message=f"El backup al NAS falló: {error}")
    _send_with_cooldown(config, SQLiteStore(config), [alert])


async def _backup_job():
    """Backup al NAS. En fallo: email + reintento antes del intervalo normal (el dato vivo
    es local y nunca se toca; ver backup.py)."""
    bcfg = config.get("backup", {})
    if not bcfg.get("enabled", False):
        return
    log.info("Backup programado al NAS")
    try:
        result = await asyncio.to_thread(backup.run_backup, config)
        if result.get("ok"):
            log.info("Backup OK: %s", result["manifest"]["counts"])
    except Exception as e:  # ConsistencyError/TransferError/inesperado
        log.exception("Backup falló")
        await asyncio.to_thread(_alert_backup_failure, e)
        retry_days = bcfg.get("retry_on_fail_days", 1)
        if _scheduler.running:
            _scheduler.add_job(_backup_job, "date",
                               run_date=timeutils.now() + timedelta(days=retry_days),
                               id="backup-retry", replace_existing=True)


async def _refresh_job():
    """Refresca el token si ya pasó la media vida del access token."""
    try:
        token = whisker_auth.load_token(config)
        fraction = config.get("schedule", {}).get("refresh_fraction", 0.5)
        if whisker_auth.needs_refresh(token, fraction):
            if await whisker_auth.refresh(config):
                log.info("Token de Whisker refrescado (media vida)")
    except whisker_auth.WhiskerAuthRequired as e:
        log.warning("Refresco imposible: %s", e)  # el ciclo de datos avisará por email
    except Exception:
        log.exception("Refresco de token falló")


def _start():
    fetch_cron = config.get("schedule", {}).get("fetch_cron", "0 */6 * * *")
    _scheduler.add_job(_fetch_job, CronTrigger.from_crontab(fetch_cron, timezone=timeutils.LOCAL_TZ),
                       id="fetch", replace_existing=True, max_instances=1, coalesce=True)
    _scheduler.add_job(_refresh_job, IntervalTrigger(minutes=15),
                       id="refresh", replace_existing=True, max_instances=1, coalesce=True)
    bcfg = config.get("backup", {})
    if bcfg.get("enabled", False):
        _scheduler.add_job(_backup_job, IntervalTrigger(days=int(bcfg.get("interval_days", 4))),
                           id="backup", replace_existing=True, max_instances=1, coalesce=True)
    _scheduler.start()
    log.info("Scheduler arrancado: fetch '%s', refresco 15 min, backup cada %s días",
             fetch_cron, config.get("backup", {}).get("interval_days", 4))


def _stop():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)


@asynccontextmanager
async def lifespan(app):
    _start()
    try:
        yield
    finally:
        _stop()


app = Starlette(
    routes=[
        Route("/whisker-login", login_form, methods=["GET"]),
        Route("/whisker-login", login_submit, methods=["POST"]),
        Route("/healthz", healthz, methods=["GET"]),
    ],
    lifespan=lifespan,
)
