"""
Guardia del límite público/privado: oauth2-proxy.cfg debe dejar SIN login solo las
rutas seguras (dashboard + canned queries) y exigir login para todo lo sensible.

Como en este diseño el candado lo pone el proxy (no una Datasette capada), este test
es la red de seguridad: si alguien afloja `skip_auth_routes`, salta aquí.
"""
import re
from pathlib import Path

import pytest

CFG = Path(__file__).parent.parent / "oauth2-proxy.cfg"

# Rutas que DEBEN ser públicas (las usa el dashboard sin login).
PUBLIC = [
    "/", "/favicon.ico", "/static/dashboard.html",
    "/weights/cat_daily.json", "/weights/box_daily.json", "/weights/robot_status.json",
]
# Rutas SENSIBLES que NO pueden quedar públicas (datos crudos, SQL, login, internals).
PROTECTED = [
    "/weights", "/weights.json", "/weights/visits.json", "/weights/visits",
    "/weights/cat_daily",            # la página HTML de la canned query, no su .json
    "/-/metadata.json", "/whisker-login", "/weights/robot_snapshots.json",
]


def _array_entries(key: str) -> list[str]:
    """Extrae las cadenas entre comillas de un array `key = [ ... ]` (línea a línea, para
    no tropezar con los corchetes de clase de regex como ``[.]``)."""
    out, collecting = [], False
    for line in CFG.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(key):
            collecting = True
            continue
        if collecting:
            if stripped == "]":
                break
            m = re.search(r'"([^"]+)"', line)
            if m:
                out.append(m.group(1))
    return out


def _skip_auth_patterns():
    entries = _array_entries("skip_auth_routes")
    assert entries, "skip_auth_routes está vacío o no se encontró"
    # Formato "METHOD=regex"; nos quedamos con el regex.
    return [e.split("=", 1)[1] for e in entries]


def _matches_any(path, patterns):
    return any(re.search(p, path) for p in patterns)


@pytest.fixture(scope="module")
def patterns():
    return _skip_auth_patterns()


@pytest.mark.parametrize("path", PUBLIC)
def test_public_paths_are_skipped(patterns, path):
    assert _matches_any(path, patterns), f"{path} debería ser público (skip_auth)"


@pytest.mark.parametrize("path", PROTECTED)
def test_protected_paths_require_auth(patterns, path):
    assert not _matches_any(path, patterns), f"{path} NO debe quedar público"


def test_upstreams_are_localhost_only(patterns):
    # Los upstreams deben apuntar a 127.0.0.1 (datasette/tracker no exponen puerto).
    upstreams = _array_entries("upstreams")
    assert upstreams
    for up in upstreams:
        assert "127.0.0.1" in up, f"upstream no-local: {up}"
