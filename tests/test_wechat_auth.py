"""Tests for the WeChat Mini Program auth endpoints.

Mocks the Tencent jscode2session call so tests run offline and don't
require real WeChat credentials. Covers the tri-state login, the
link-with-password path, and the invitation-aware register path.
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixture: fresh DB + TestClient + deterministic WeChat mock
# ---------------------------------------------------------------------------


@pytest.fixture
def wechat_client(monkeypatch):
    """A FastAPI TestClient wired to a fresh SQLite DB with a stubbed WeChat API.

    `wechat_mock` is attached to the yielded client so individual tests can
    program the openid/unionid returned by the fake jscode2session call.
    """
    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    monkeypatch.setenv("DATA_DIR", tmpdir.name)
    monkeypatch.setenv("TRAINSIGHT_SYNC_SCHEDULER", "false")
    monkeypatch.setenv(
        "TRAINSIGHT_LOCAL_ENCRYPTION_KEY",
        "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=",
    )
    # Do NOT override TRAINSIGHT_JWT_SECRET. The api.auth module caches
    # JWT_SECRET at import time and is shared across tests; using the default
    # secret keeps api.users and api.auth in agreement on the signing key.
    monkeypatch.setenv("WECHAT_MINIAPP_APPID", "test-appid")
    monkeypatch.setenv("WECHAT_MINIAPP_SECRET", "test-secret")
    monkeypatch.setenv("TRAINSIGHT_ADMIN_EMAIL", "")

    from db import session as db_session
    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    # Reload modules that cached SECRET / ADMIN_EMAIL at import time.
    import importlib
    import api.users
    import api.invitations
    import api.routes.wechat
    importlib.reload(api.users)
    importlib.reload(api.invitations)
    importlib.reload(api.routes.wechat)

    # Rebuild the app so include_router() picks up the reloaded modules.
    import api.main
    importlib.reload(api.main)
    app = api.main.app

    # Replace the jscode2session call with a programmable stub.
    class WeChatMock:
        def __init__(self):
            # Default to returning a fresh openid; tests override as needed.
            self.next_openid = "openid-default"
            self.next_unionid = None
            self.should_fail = None  # set to (status_code, detail) to force an error

        async def fake(self, js_code: str) -> dict:
            if self.should_fail:
                from fastapi import HTTPException
                code, detail = self.should_fail
                raise HTTPException(code, detail)
            return {
                "openid": self.next_openid,
                "unionid": self.next_unionid,
                "session_key": "stub-session-key",
            }

    mock = WeChatMock()
    monkeypatch.setattr(api.routes.wechat, "_jscode2session", mock.fake)

    client = TestClient(app)
    client.wechat_mock = mock  # type: ignore[attr-defined]
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
        try:
            if db_session.engine is not None:
                db_session.engine.dispose()
        except Exception:
            pass
        try:
            tmpdir.cleanup()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# /auth/wechat/login
# ---------------------------------------------------------------------------


def test_login_new_user_returns_setup_ticket(wechat_client):
    wechat_client.wechat_mock.next_openid = "openid-alice"
    r = wechat_client.post("/api/auth/wechat/login", json={"js_code": "code-1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "needs_setup"
    assert body["access_token"] is None
    assert body["wechat_login_ticket"]

    # Ticket carries the openid under the right audience.
    from api.auth_secrets import get_jwt_secret
    decoded = pyjwt.decode(
        body["wechat_login_ticket"],
        get_jwt_secret(),
        algorithms=["HS256"],
        audience="trainsight:wechat-setup",
    )
    assert decoded["sub"] == "openid-alice"


def test_login_returning_user_gets_jwt(wechat_client):
    # Bootstrap: register a new user via the WeChat register endpoint first.
    wechat_client.wechat_mock.next_openid = "openid-bob"
    login = wechat_client.post("/api/auth/wechat/login", json={"js_code": "c1"})
    ticket = login.json()["wechat_login_ticket"]
    reg = wechat_client.post(
        "/api/auth/wechat/register",
        json={"wechat_login_ticket": ticket, "invitation_code": ""},
    )
    assert reg.status_code == 200, reg.text

    # Now a second login should short-circuit to status=ok + JWT.
    r = wechat_client.post("/api/auth/wechat/login", json={"js_code": "c2"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["access_token"]
    assert body["wechat_login_ticket"] is None


def test_jscode2session_without_config_raises_503(monkeypatch):
    """Unit test the helper directly — going through the full TestClient
    plus an importlib.reload to "unload" the wechat mock ends up
    re-running api.main's load_dotenv(), which silently restores any
    real credentials a developer has in their local .env. Testing the
    helper in isolation avoids that fragility entirely."""
    import asyncio
    from fastapi import HTTPException
    import api.routes.wechat as wechat_routes

    monkeypatch.setenv("WECHAT_MINIAPP_APPID", "")
    monkeypatch.setenv("WECHAT_MINIAPP_SECRET", "")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(wechat_routes._jscode2session("any-code"))
    assert exc_info.value.status_code == 503
    assert "WECHAT_NOT_CONFIGURED" in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# /auth/wechat/register
# ---------------------------------------------------------------------------


def _get_ticket(client, openid: str, unionid: str | None = None) -> str:
    client.wechat_mock.next_openid = openid
    client.wechat_mock.next_unionid = unionid
    r = client.post("/api/auth/wechat/login", json={"js_code": f"c-{openid}"})
    return r.json()["wechat_login_ticket"]


def test_register_first_user_becomes_admin_no_invite(wechat_client):
    ticket = _get_ticket(wechat_client, "openid-first")
    r = wechat_client.post(
        "/api/auth/wechat/register",
        json={"wechat_login_ticket": ticket, "invitation_code": ""},
    )
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]

    # The issued JWT should grant access to /api/auth/me (real auth middleware).
    me = wechat_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["is_superuser"] is True
    # WeChat-only users get a deterministic sentinel in the email column.
    assert body["email"] == "wechat:openid-first"


def test_register_second_user_without_invite_fails(wechat_client):
    # First user seeds the DB.
    first_ticket = _get_ticket(wechat_client, "openid-one")
    wechat_client.post(
        "/api/auth/wechat/register",
        json={"wechat_login_ticket": first_ticket, "invitation_code": ""},
    )

    # Second user has no invitation.
    second_ticket = _get_ticket(wechat_client, "openid-two")
    r = wechat_client.post(
        "/api/auth/wechat/register",
        json={"wechat_login_ticket": second_ticket, "invitation_code": ""},
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "REGISTER_INVITATION_REQUIRED"


def test_register_second_user_with_valid_invite_succeeds(wechat_client):
    # Bootstrap an admin.
    admin_ticket = _get_ticket(wechat_client, "openid-admin")
    admin_reg = wechat_client.post(
        "/api/auth/wechat/register",
        json={"wechat_login_ticket": admin_ticket, "invitation_code": ""},
    )
    admin_token = admin_reg.json()["access_token"]

    # Admin creates an invitation via the admin API.
    inv_resp = wechat_client.post(
        "/api/admin/invitations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"note": "test"},
    )
    assert inv_resp.status_code in (200, 201), inv_resp.text
    code = inv_resp.json()["code"]

    # Second user registers with the invite.
    second_ticket = _get_ticket(wechat_client, "openid-invitee")
    r = wechat_client.post(
        "/api/auth/wechat/register",
        json={"wechat_login_ticket": second_ticket, "invitation_code": code},
    )
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]

    # Re-using the same invite must fail.
    third_ticket = _get_ticket(wechat_client, "openid-leech")
    r2 = wechat_client.post(
        "/api/auth/wechat/register",
        json={"wechat_login_ticket": third_ticket, "invitation_code": code},
    )
    assert r2.status_code == 400


def test_register_openid_already_bound_conflicts(wechat_client):
    ticket = _get_ticket(wechat_client, "openid-x")
    wechat_client.post(
        "/api/auth/wechat/register",
        json={"wechat_login_ticket": ticket, "invitation_code": ""},
    )

    # Try to register again with the same ticket (and therefore same openid).
    r = wechat_client.post(
        "/api/auth/wechat/register",
        json={"wechat_login_ticket": ticket, "invitation_code": ""},
    )
    assert r.status_code == 409
    assert "WECHAT_REGISTER_OPENID_ALREADY_BOUND" in r.text


def test_register_with_email_password_stores_both(wechat_client):
    ticket = _get_ticket(wechat_client, "openid-web")
    r = wechat_client.post(
        "/api/auth/wechat/register",
        json={
            "wechat_login_ticket": ticket,
            "invitation_code": "",
            "email": "alice@example.com",
            "password": "hunter2-longish",
        },
    )
    assert r.status_code == 200, r.text

    me = wechat_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {r.json()['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"


# ---------------------------------------------------------------------------
# /auth/wechat/link-with-password
# ---------------------------------------------------------------------------


def test_link_with_password_binds_openid_to_existing_account(wechat_client):
    # Existing web user (registered via the normal route).
    # First register as admin with email+password via the WeChat register path
    # (gives us a password we know; the normal register endpoint works too).
    admin_ticket = _get_ticket(wechat_client, "openid-seed-admin")
    wechat_client.post(
        "/api/auth/wechat/register",
        json={"wechat_login_ticket": admin_ticket, "invitation_code": ""},
    )

    # Now create a *separate* web-style user via the normal /api/auth/register,
    # with invitation code from admin.
    # Simpler: register a user directly using the WeChat register with email+pass,
    # then pretend they never bound WeChat. Achieve that by:
    #   1. Create user with email+pass via wechat register (binds openid A)
    #   2. Unbind openid A manually through a fresh openid B linking flow
    # Easier: use the FastAPI-Users normal register endpoint via admin-issued invite.

    # Admin invite
    admin_login = wechat_client.post(
        "/api/auth/wechat/login",
        json={"js_code": "c-seed-admin-reuse"},
    )
    admin_token = admin_login.json()["access_token"]
    inv = wechat_client.post(
        "/api/admin/invitations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"note": "for web user"},
    )
    invite_code = inv.json()["code"]

    reg = wechat_client.post(
        "/api/auth/register",
        json={
            "email": "bob@example.com",
            "password": "correct-horse-battery",
            "invitation_code": invite_code,
        },
    )
    assert reg.status_code == 200, reg.text

    # Now Bob opens the mini program for the first time. openid unknown → needs_setup.
    setup_ticket = _get_ticket(wechat_client, "openid-bob-phone")

    # Bob picks "I already have an account" and types his email+password.
    link = wechat_client.post(
        "/api/auth/wechat/link-with-password",
        json={
            "wechat_login_ticket": setup_ticket,
            "email": "bob@example.com",
            "password": "correct-horse-battery",
        },
    )
    assert link.status_code == 200, link.text
    token = link.json()["access_token"]

    me = wechat_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "bob@example.com"

    # Subsequent WeChat logins now go straight to status=ok.
    wechat_client.wechat_mock.next_openid = "openid-bob-phone"
    second = wechat_client.post("/api/auth/wechat/login", json={"js_code": "c-x"})
    assert second.json()["status"] == "ok"


def test_link_with_password_wrong_password_rejected(wechat_client):
    # Seed admin + invited web user exactly as above.
    admin_ticket = _get_ticket(wechat_client, "openid-admin-2")
    wechat_client.post(
        "/api/auth/wechat/register",
        json={"wechat_login_ticket": admin_ticket, "invitation_code": ""},
    )
    admin_token = wechat_client.post(
        "/api/auth/wechat/login", json={"js_code": "c-a2"}
    ).json()["access_token"]
    invite_code = wechat_client.post(
        "/api/admin/invitations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"note": "x"},
    ).json()["code"]
    wechat_client.post(
        "/api/auth/register",
        json={
            "email": "carol@example.com",
            "password": "real-password-abc",
            "invitation_code": invite_code,
        },
    )

    setup_ticket = _get_ticket(wechat_client, "openid-carol")
    r = wechat_client.post(
        "/api/auth/wechat/link-with-password",
        json={
            "wechat_login_ticket": setup_ticket,
            "email": "carol@example.com",
            "password": "wrong-password",
        },
    )
    assert r.status_code == 400
    assert "WECHAT_LINK_INVALID_CREDENTIALS" in r.text


def test_link_with_expired_ticket_rejected(wechat_client):
    # Manually forge an expired ticket with the real secret.
    from api.auth_secrets import get_jwt_secret
    expired = pyjwt.encode(
        {
            "sub": "openid-expired",
            "aud": "trainsight:wechat-setup",
            "iat": datetime.utcnow() - timedelta(hours=2),
            "exp": datetime.utcnow() - timedelta(hours=1),
        },
        get_jwt_secret(),
        algorithm="HS256",
    )
    r = wechat_client.post(
        "/api/auth/wechat/link-with-password",
        json={
            "wechat_login_ticket": expired,
            "email": "anyone@example.com",
            "password": "whatever-long",
        },
    )
    assert r.status_code == 400
    assert "WECHAT_TICKET_EXPIRED" in r.text


def test_link_refuses_to_rebind_account_with_different_openid(wechat_client):
    # Bootstrap admin + one web user linked to openid-phone-A.
    admin_ticket = _get_ticket(wechat_client, "openid-admin-3")
    wechat_client.post(
        "/api/auth/wechat/register",
        json={"wechat_login_ticket": admin_ticket, "invitation_code": ""},
    )
    admin_token = wechat_client.post(
        "/api/auth/wechat/login", json={"js_code": "c-a3"}
    ).json()["access_token"]
    invite_code = wechat_client.post(
        "/api/admin/invitations",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"note": "x"},
    ).json()["code"]
    wechat_client.post(
        "/api/auth/register",
        json={
            "email": "dan@example.com",
            "password": "pw-dan-12345",
            "invitation_code": invite_code,
        },
    )
    # First link with phone-A openid.
    setup_a = _get_ticket(wechat_client, "openid-dan-phone-A")
    first = wechat_client.post(
        "/api/auth/wechat/link-with-password",
        json={
            "wechat_login_ticket": setup_a,
            "email": "dan@example.com",
            "password": "pw-dan-12345",
        },
    )
    assert first.status_code == 200

    # Second link attempt from phone-B openid (different device / re-install).
    # For now we block this — the user would need to unlink first via a future UI.
    setup_b = _get_ticket(wechat_client, "openid-dan-phone-B")
    second = wechat_client.post(
        "/api/auth/wechat/link-with-password",
        json={
            "wechat_login_ticket": setup_b,
            "email": "dan@example.com",
            "password": "pw-dan-12345",
        },
    )
    assert second.status_code == 409
    assert "WECHAT_LINK_ACCOUNT_ALREADY_LINKED" in second.text
