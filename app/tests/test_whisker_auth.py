"""Token de Whisker: persistencia 600, decodificación del JWT y lógica de media vida."""
import base64
import json
import os
import stat
from datetime import datetime, timedelta, timezone

import pytest

import whisker_auth


def _jwt(iat: datetime, exp: datetime) -> str:
    """Construye un JWT de pega con iat/exp (firma irrelevante: no se valida)."""
    def b64(obj):
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    payload = {"iat": int(iat.timestamp()), "exp": int(exp.timestamp())}
    return f"{b64({'alg': 'none'})}.{b64(payload)}.sig"


def _config(tmp_path):
    return {"whisker": {"token_path": str(tmp_path / "whisker_token.json")}}


class TestPersistence:
    def test_load_missing_is_none(self, tmp_path):
        assert whisker_auth.load_token(_config(tmp_path)) is None
        assert whisker_auth.has_token(_config(tmp_path)) is False

    def test_save_then_load_roundtrip(self, tmp_path):
        cfg = _config(tmp_path)
        tok = {"access_token": "a", "id_token": "b", "refresh_token": "c"}
        whisker_auth.save_token(cfg, tok)
        assert whisker_auth.load_token(cfg) == tok
        assert whisker_auth.has_token(cfg) is True

    def test_saved_file_is_600(self, tmp_path):
        cfg = _config(tmp_path)
        whisker_auth.save_token(cfg, {"access_token": "x"})
        mode = stat.S_IMODE(os.stat(whisker_auth.token_path(cfg)).st_mode)
        # En POSIX debe ser exactamente 600; en Windows el bit de grupo/otros no aplica.
        if os.name == "posix":
            assert mode == 0o600

    def test_empty_token_does_not_overwrite(self, tmp_path):
        cfg = _config(tmp_path)
        whisker_auth.save_token(cfg, {"access_token": "good"})
        whisker_auth.save_token(cfg, None)
        whisker_auth.save_token(cfg, {})
        assert whisker_auth.load_token(cfg) == {"access_token": "good"}

    def test_corrupt_file_reads_as_none(self, tmp_path):
        cfg = _config(tmp_path)
        whisker_auth.token_path(cfg).write_text("{not json", encoding="utf-8")
        assert whisker_auth.load_token(cfg) is None


class TestRefreshTiming:
    def _now(self):
        return datetime.now(timezone.utc)

    def test_fresh_token_does_not_need_refresh(self):
        now = self._now()
        tok = {"access_token": _jwt(now, now + timedelta(hours=1))}
        assert whisker_auth.needs_refresh(tok, fraction=0.5) is False

    def test_past_half_life_needs_refresh(self):
        now = self._now()
        # Emitido hace 40 min, vida de 1h → ya pasó la mitad.
        tok = {"access_token": _jwt(now - timedelta(minutes=40), now + timedelta(minutes=20))}
        assert whisker_auth.needs_refresh(tok, fraction=0.5) is True

    def test_expired_needs_refresh(self):
        now = self._now()
        tok = {"access_token": _jwt(now - timedelta(hours=2), now - timedelta(hours=1))}
        assert whisker_auth.needs_refresh(tok) is True

    def test_unparseable_token_refreshes_to_be_safe(self):
        assert whisker_auth.needs_refresh({"access_token": "no-es-jwt"}) is True

    def test_none_token_does_not_refresh(self):
        assert whisker_auth.needs_refresh(None) is False
