"""
Plugin de Datasette: botón flotante "Cerrar sesión" en las páginas del explorador.

Solo aparece en páginas HTML de Datasette (el explorador, que está tras login). El
dashboard de ``/`` lo sirve homepage.py como HTML plano, así que ahí no se inyecta.
El botón va a ``/oauth2/sign_out`` (oauth2-proxy borra la cookie y vuelve al dashboard).
"""
from datasette import hookimpl

_LOGOUT_BUTTON = """
(function () {
  var a = document.createElement('a');
  a.href = '/oauth2/sign_out?rd=/';
  a.textContent = 'Cerrar sesión';
  a.title = 'Cerrar sesión y volver al dashboard';
  a.style.cssText = [
    'position:fixed', 'top:10px', 'right:12px', 'z-index:10000',
    'background:#fff', 'border:1px solid #ccc', 'border-radius:4px',
    'padding:6px 12px', 'font:13px/1 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',
    'color:#444', 'text-decoration:none', 'box-shadow:0 1px 3px rgba(0,0,0,.15)'
  ].join(';');
  a.onmouseover = function () { a.style.background = '#ececec'; };
  a.onmouseout = function () { a.style.background = '#fff'; };
  document.body.appendChild(a);
})();
"""


@hookimpl
def extra_body_script():
    return _LOGOUT_BUTTON
