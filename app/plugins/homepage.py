"""
Plugin de Datasette (instancia única, tras oauth2-proxy).

- Sirve el dashboard en la raíz ``/`` (sin redirect). oauth2-proxy deja ``/`` público;
  el resto de Datasette (tablas, SQL) exige login. Así ``/`` es el dashboard y el
  explorador crudo queda detrás de la autenticación.
- Sirve el favicon en ``/favicon.ico`` (donde el navegador lo pide por defecto).
"""
from pathlib import Path

from datasette import hookimpl
from datasette.utils.asgi import Response

STATIC = Path("/app/static")


async def serve_dashboard(request):
    return Response.html((STATIC / "dashboard.html").read_text(encoding="utf-8"))


async def serve_favicon(request):
    return Response(
        body=(STATIC / "favicon.ico").read_bytes(),
        content_type="image/x-icon",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@hookimpl
def register_routes():
    return [
        (r"^/$", serve_dashboard),
        (r"^/favicon.ico$", serve_favicon),
    ]
