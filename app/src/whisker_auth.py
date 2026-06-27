"""
Autenticación con Whisker por TOKEN (no por contraseña).

El password solo se usa **una vez**, en el formulario web (`/whisker-login`), para
emitir un token; a partir de ahí se guarda y se refresca el token. El fichero del
token es un secreto (600, propiedad del usuario `tracker`). Si no hay token o ya no
vale, el ciclo avisa por email con el enlace al formulario.

El token de Whisker es un dict ``{access_token, id_token, refresh_token}``. Los dos
primeros son JWT con ``exp``/``iat`` legibles; el refresh token es opaco. "Media vida"
se calcula sobre el access token.
"""
import base64
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from pylitterbot import Account
from pylitterbot.exceptions import LitterRobotLoginException

log = logging.getLogger(__name__)

DEFAULT_TOKEN_PATH = "/data/whisker_token.json"
_ASSUMED_ACCESS_TTL = timedelta(hours=1)  # si el JWT no trae iat


class WhiskerAuthRequired(Exception):
    """No hay token válido: hace falta (re)iniciar sesión vía el formulario web."""


# ── Persistencia del token ────────────────────────────────────────────────────
def token_path(config: dict) -> Path:
    return Path(config.get("whisker", {}).get("token_path", DEFAULT_TOKEN_PATH))


def load_token(config: dict) -> Optional[dict]:
    path = token_path(config)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Token de Whisker ilegible (%s): %s", path, e)
        return None
    return data or None


def save_token(config: dict, tokens: Optional[dict]) -> None:
    """Guarda el token con permisos 600. Ignora un token vacío (no pisar uno bueno)."""
    if not tokens:
        return
    path = token_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    # O_CREAT con 0o600 + chmod para forzar permisos aunque el fichero ya existiera.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(tokens, f)
    os.chmod(path, 0o600)
    log.info("Token de Whisker guardado en %s", path)


def has_token(config: dict) -> bool:
    return load_token(config) is not None


# ── Vida del access token (JWT) ───────────────────────────────────────────────
def _decode_exp_iat(jwt: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """Devuelve (exp, iat) del payload de un JWT, sin validar firma (es nuestro)."""
    try:
        payload_b64 = jwt.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # repón el padding base64url
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    except Exception:  # pragma: no cover - token con formato inesperado
        return None, None

    def _dt(ts) -> Optional[datetime]:
        return datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None

    return _dt(payload.get("exp")), _dt(payload.get("iat"))


def needs_refresh(token: Optional[dict], fraction: float = 0.5) -> bool:
    """¿Ha pasado ya `fraction` de la vida del access token? (caducado → True)."""
    if not token:
        return False
    exp, iat = _decode_exp_iat(token.get("access_token", ""))
    if exp is None:
        return True  # no sabemos su vida → refresca por seguridad
    if iat is None:
        iat = exp - _ASSUMED_ACCESS_TTL
    now = datetime.now(timezone.utc)
    return now >= iat + (exp - iat) * fraction


# ── Operaciones con la cuenta ──────────────────────────────────────────────────
async def login_and_store(config: dict, username: str, password: str) -> dict:
    """Login con user+password UNA vez → guarda el token y lo devuelve.

    El password no se almacena en ningún sitio. Lanza ``LitterRobotLoginException``
    si las credenciales son incorrectas (lo gestiona el formulario).
    """
    account = Account()
    try:
        await account.connect(username=username, password=password)
        tokens = account.session.tokens
        if not tokens:
            raise WhiskerAuthRequired("Whisker no devolvió token tras el login")
        save_token(config, tokens)
        return tokens
    finally:
        await account.disconnect()


async def connect_with_token(config: dict, load_robots: bool = True,
                             load_pets: bool = False) -> Account:
    """Crea y conecta una Account con el token almacenado (sin password).

    El `token_update_callback` persiste el token rotado. Si no hay token o ya no es
    válido, lanza ``WhiskerAuthRequired`` (un fallo de red NO lo dispara: propaga).
    """
    tokens = load_token(config)
    if not tokens:
        raise WhiskerAuthRequired("No hay token de Whisker almacenado")

    account = Account(token=tokens, token_update_callback=lambda t: save_token(config, t))
    try:
        await account.connect(load_robots=load_robots, load_pets=load_pets)
    except LitterRobotLoginException as e:
        raise WhiskerAuthRequired(f"El token de Whisker ya no es válido: {e}") from e
    return account


async def refresh(config: dict) -> bool:
    """Fuerza el refresco del token almacenado. True si se refrescó, False si no hay token.

    Un fallo de login (refresh token caducado) se traduce en ``WhiskerAuthRequired``.
    """
    tokens = load_token(config)
    if not tokens:
        return False

    account = Account(token=tokens, token_update_callback=lambda t: save_token(config, t))
    try:
        await account.session.refresh_tokens(ignore_unexpired=True)
        if account.session.tokens:  # persiste aunque el callback no se disparara
            save_token(config, account.session.tokens)
        return True
    except LitterRobotLoginException as e:
        raise WhiskerAuthRequired(f"No se pudo refrescar el token: {e}") from e
    finally:
        await account.disconnect()
