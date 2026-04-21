import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from sync.strava_sync import DEFAULT_SCOPE
from tests.test_settings_api import api_client


@pytest.fixture(autouse=True)
def reset_vault():
    from db import crypto

    crypto._vault = None
    try:
        yield
    finally:
        crypto._vault = None


@pytest.fixture(autouse=True)
def clear_strava_redirect_override(monkeypatch):
    monkeypatch.delenv("PRAXYS_STRAVA_REDIRECT_URI", raising=False)
    monkeypatch.delenv("TRAINSIGHT_STRAVA_REDIRECT_URI", raising=False)


def _load_strava_connection(user_id: str):
    from db import session as db_session
    from db.crypto import get_vault
    from db.models import UserConnection

    db = db_session.SessionLocal()
    try:
        conn = (
            db.query(UserConnection)
            .filter(
                UserConnection.user_id == user_id,
                UserConnection.platform == "strava",
            )
            .first()
        )
        if not conn:
            return None
        creds = json.loads(
            get_vault().decrypt(conn.encrypted_credentials, conn.wrapped_dek)
        )
        return {
            "status": conn.status,
            "preferences": conn.preferences,
            "credentials": creds,
        }
    finally:
        db.close()


def test_start_strava_oauth_returns_signed_authorize_url(api_client, monkeypatch):
    client, user_id = api_client
    monkeypatch.setenv("PRAXYS_STRAVA_CLIENT_ID", "55555")
    monkeypatch.setenv("PRAXYS_STRAVA_CLIENT_SECRET", "secret-value")

    res = client.post(
        "/api/settings/connections/strava/start",
        json={
            "web_origin": "https://app.example.test",
            "return_to": "/settings?tab=connections",
        },
    )

    assert res.status_code == 200, res.text
    authorize_url = res.json()["authorize_url"]
    parsed = urlparse(authorize_url)
    params = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "www.strava.com"
    assert parsed.path == "/oauth/authorize"
    assert params["client_id"] == ["55555"]
    assert params["response_type"] == ["code"]
    assert params["approval_prompt"] == ["auto"]
    assert params["scope"] == [DEFAULT_SCOPE]
    redirect_uri = urlparse(params["redirect_uri"][0])
    assert redirect_uri.scheme == "http"
    assert redirect_uri.path == "/api/settings/connections/strava/callback"

    from api.routes.settings import _decode_strava_state

    payload = _decode_strava_state(params["state"][0])
    assert payload["sub"] == user_id
    assert payload["purpose"] == "strava_connect"
    assert payload["web_origin"] == "https://app.example.test"
    assert payload["return_to"] == "/settings?tab=connections"


def test_start_strava_oauth_requires_client_config(api_client, monkeypatch):
    client, _user_id = api_client
    monkeypatch.delenv("PRAXYS_STRAVA_CLIENT_ID", raising=False)
    monkeypatch.delenv("PRAXYS_STRAVA_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("TRAINSIGHT_STRAVA_CLIENT_ID", raising=False)
    monkeypatch.delenv("TRAINSIGHT_STRAVA_CLIENT_SECRET", raising=False)

    res = client.post(
        "/api/settings/connections/strava/start",
        json={"web_origin": "https://app.example.test"},
    )

    assert res.status_code == 503, res.text
    assert "Strava OAuth is not configured" in res.json()["detail"]


def test_strava_oauth_callback_persists_encrypted_connection_and_sync_status(
    api_client,
    monkeypatch,
):
    client, user_id = api_client
    monkeypatch.setenv("PRAXYS_STRAVA_CLIENT_ID", "55555")
    monkeypatch.setenv("PRAXYS_STRAVA_CLIENT_SECRET", "secret-value")

    from api.routes.settings import _encode_strava_state

    state = _encode_strava_state(
        user_id,
        "https://app.example.test",
        "/settings/connections",
    )

    with (
        patch("sync.strava_sync.exchange_code_for_token") as mock_exchange,
        patch("sync.strava_sync.fetch_athlete_api") as mock_fetch_athlete,
    ):
        mock_exchange.return_value = {
            "access_token": "token-1",
            "refresh_token": "refresh-1",
            "expires_at": 1776000000,
            "expires_in": 21600,
        }
        mock_fetch_athlete.return_value = {"id": 42, "username": "runner-42"}

        res = client.get(
            "/api/settings/connections/strava/callback",
            params={
                "code": "auth-code",
                "scope": DEFAULT_SCOPE,
                "state": state,
            },
            follow_redirects=False,
        )

    assert res.status_code == 307, res.text
    assert (
        res.headers["location"]
        == "https://app.example.test/settings/connections?strava=connected"
    )
    mock_exchange.assert_called_once_with("auth-code", "55555", "secret-value")
    mock_fetch_athlete.assert_called_once_with("token-1")

    conn = _load_strava_connection(user_id)
    assert conn == {
        "status": "connected",
        "preferences": {"activities": True},
        "credentials": {
            "access_token": "token-1",
            "refresh_token": "refresh-1",
            "expires_at": 1776000000,
            "expires_in": 21600,
            "scope": DEFAULT_SCOPE,
            "athlete": {"id": 42, "username": "runner-42"},
        },
    }

    status_res = client.get("/api/sync/status")
    assert status_res.status_code == 200, status_res.text
    sync_status = status_res.json()
    assert sync_status["strava"]["status"] == "idle"
    assert sync_status["strava"]["connected"] is True
    assert sync_status["strava"]["last_sync"] is None
    assert sync_status["strava"]["error"] is None


def test_strava_oauth_callback_redirects_error_without_writing_connection(
    api_client,
    monkeypatch,
):
    client, user_id = api_client
    monkeypatch.setenv("PRAXYS_STRAVA_CLIENT_ID", "55555")
    monkeypatch.setenv("PRAXYS_STRAVA_CLIENT_SECRET", "secret-value")

    from api.routes.settings import _encode_strava_state

    state = _encode_strava_state(user_id, "https://app.example.test", "/settings")

    res = client.get(
        "/api/settings/connections/strava/callback",
        params={
            "error": "access_denied",
            "state": state,
        },
        follow_redirects=False,
    )

    assert res.status_code == 307, res.text
    assert (
        res.headers["location"]
        == "https://app.example.test/settings?strava=error&strava_message=access_denied"
    )
    assert _load_strava_connection(user_id) is None
