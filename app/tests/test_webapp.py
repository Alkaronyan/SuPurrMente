"""Formulario /whisker-login: render, CSRF double-submit, login OK/erróneo."""
import pytest
from pylitterbot.exceptions import LitterRobotLoginException
from starlette.testclient import TestClient

import webapp
import whisker_auth


@pytest.fixture
def client(monkeypatch):
    # Sin `with`: no se disparan los eventos startup → el scheduler no arranca en tests.
    # Cookie no-secure para que el TestClient (http) la reenvíe.
    monkeypatch.setattr(webapp, "COOKIE_SECURE", False)
    return TestClient(webapp.app)


def _get_csrf(client):
    r = client.get("/whisker-login")
    assert r.status_code == 200
    assert "Conectar con Whisker" in r.text
    return client.cookies.get(webapp.CSRF_COOKIE)


def test_healthz(client):
    assert client.get("/healthz").text == "ok"


def test_form_sets_csrf_cookie(client):
    assert _get_csrf(client)  # cookie presente


def test_post_without_csrf_is_rejected(client):
    r = client.post("/whisker-login", data={"username": "x@y.com", "password": "p"})
    assert r.status_code == 400


def test_successful_login_stores_token(client, monkeypatch):
    called = {}

    async def fake_login(config, username, password):
        called["user"] = username
        called["pass"] = password
        return {"access_token": "a"}

    monkeypatch.setattr(whisker_auth, "login_and_store", fake_login)
    csrf = _get_csrf(client)
    r = client.post("/whisker-login",
                    data={"csrf": csrf, "username": "yo@gonzalez.team", "password": "secreta"})
    assert r.status_code == 200
    assert "Conectado con Whisker" in r.text
    assert called == {"user": "yo@gonzalez.team", "pass": "secreta"}


def test_bad_credentials_show_error(client, monkeypatch):
    async def fake_login(config, username, password):
        raise LitterRobotLoginException("nope")

    monkeypatch.setattr(whisker_auth, "login_and_store", fake_login)
    csrf = _get_csrf(client)
    r = client.post("/whisker-login",
                    data={"csrf": csrf, "username": "yo@gonzalez.team", "password": "mala"})
    assert r.status_code == 401
    assert "incorrectos" in r.text


def test_missing_fields_rejected(client):
    csrf = _get_csrf(client)
    r = client.post("/whisker-login", data={"csrf": csrf, "username": "", "password": ""})
    assert r.status_code == 400
