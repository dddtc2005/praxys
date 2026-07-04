"""Integration tests for open self-registration: the gate, seat cap (committed
seats), email verification, honeypot, invitation expiry, admin config, and the
waitlist-invite flow.

Uses the same fresh-DB TestClient pattern as tests/test_waitlist.py, with SMTP
env set so the verification path is active and email_sender.send_email patched
to capture the verification token / invitation email.
"""
from __future__ import annotations

import importlib
import re
import tempfile
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient


def _build(monkeypatch, data_dir: str):
    monkeypatch.setenv("DATA_DIR", data_dir)
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "false")
    monkeypatch.setenv(
        "PRAXYS_LOCAL_ENCRYPTION_KEY",
        "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=",
    )
    monkeypatch.setenv("PRAXYS_AUTH_RATE_LIMIT_DISABLED", "true")
    monkeypatch.setenv("PRAXYS_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("PRAXYS_SMTP_USER", "no-reply@praxys.run")
    monkeypatch.setenv("PRAXYS_SMTP_PASSWORD", "dummy")
    monkeypatch.delenv("WECHAT_MINIAPP_APPID", raising=False)
    monkeypatch.delenv("WECHAT_MINIAPP_SECRET", raising=False)
    monkeypatch.delenv("PRAXYS_ADMIN_EMAIL", raising=False)

    from db import session as db_session

    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    import api.users
    import api.invitations
    import api.app_config

    importlib.reload(api.invitations)
    importlib.reload(api.app_config)
    importlib.reload(api.users)

    import api.main

    importlib.reload(api.main)
    return api.main, db_session


@pytest.fixture
def env(monkeypatch):
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        main, db_session = _build(monkeypatch, tmp.name)
        import api.email_sender as es

        captured = {"tokens": [], "emails": []}

        def fake_send(to, subject, text, html=None):
            captured["emails"].append({"to": to, "subject": subject, "text": text})
            m = re.search(r"/verify\?token=([^\s]+)", text or "")
            if m:
                captured["tokens"].append(m.group(1))
            return True

        monkeypatch.setattr(es, "send_email", fake_send)
        with TestClient(main.app) as client:
            yield client, db_session, captured
    finally:
        try:
            if db_session.engine is not None:
                db_session.engine.dispose()
        except Exception:
            pass
        tmp.cleanup()


# --- helpers ---------------------------------------------------------------

def _reg(client, email, **kw):
    body = {"email": email, "password": "pw123456", "accepted_terms": True}
    body.update(kw)
    return client.post("/api/auth/register", json=body)


def _login(client, email, pw="pw123456"):
    return client.post("/api/auth/login", data={"username": email, "password": pw})


def _admin_token(client):
    _reg(client, "admin@praxys.run")  # first user -> admin, verified
    return _login(client, "admin@praxys.run").json()["access_token"]


def _open_gate(db_session, max_users=100):
    from api import app_config
    db = db_session.SessionLocal()
    app_config.set_value(db, app_config.KEY_REGISTRATION_OPEN, "true")
    app_config.set_value(db, app_config.KEY_REGISTRATION_MAX_USERS, str(max_users))
    db.close()


# --- app_config unit-ish ---------------------------------------------------

def test_app_config_defaults_and_committed_seats(env):
    client, db_session, _ = env
    from api import app_config
    from db.models import Invitation

    db = db_session.SessionLocal()
    assert app_config.is_registration_open(db) == (False, "closed_flag")

    app_config.set_value(db, app_config.KEY_REGISTRATION_OPEN, "true")
    app_config.set_value(db, app_config.KEY_REGISTRATION_MAX_USERS, "3")
    assert app_config.is_registration_open(db) == (True, "open")

    # An active/unused/unexpired invitation reserves a committed seat.
    db.add(Invitation(code="TS-AAAA-0001", created_by="x"))
    # An expired one does NOT count.
    db.add(Invitation(code="TS-AAAA-0002", created_by="x",
                      expires_at=datetime.utcnow() - timedelta(days=1)))
    db.commit()
    status = app_config.registration_status(db)
    assert status["outstanding_invitations"] == 1
    assert status["committed_seats"] == status["registered_users"] + 1

    app_config.set_value(db, app_config.KEY_REGISTRATION_MAX_USERS, "1")
    assert app_config.is_registration_open(db) == (False, "cap_reached")
    db.close()


# --- register paths --------------------------------------------------------

def test_first_user_is_admin_and_can_login(env):
    client, _, _ = env
    r = _reg(client, "admin@praxys.run")
    assert r.status_code == 200
    assert r.json()["is_superuser"] is True
    assert "access_token" in _login(client, "admin@praxys.run").json()


def test_honeypot_rejected(env):
    client, _, _ = env
    _admin_token(client)
    r = _reg(client, "bot@x.com", website="http://spam")
    assert r.status_code == 400
    assert r.json()["detail"] == "REGISTER_FAILED"


def test_closed_gate_blocks_codeless_signup(env):
    client, _, _ = env
    _admin_token(client)  # gate is closed by default
    r = _reg(client, "stranger@x.com")
    assert r.status_code == 403
    assert r.json()["detail"] == "REGISTER_CLOSED"


def test_open_signup_requires_verification_then_login(env):
    client, db_session, captured = env
    _admin_token(client)
    _open_gate(db_session, max_users=100)

    r = _reg(client, "carol@x.com")
    assert r.status_code == 200
    assert r.json() == {"verification_required": True, "email": "carol@x.com"}

    # Cannot log in until verified.
    blocked = _login(client, "carol@x.com")
    assert blocked.status_code == 400
    assert blocked.json()["detail"] == "LOGIN_USER_NOT_VERIFIED"

    # A verification token was emailed; use it.
    assert captured["tokens"], "expected a verification token to be emailed"
    verify = client.post("/api/auth/verify", json={"token": captured["tokens"][-1]})
    assert verify.status_code == 200
    assert "access_token" in _login(client, "carol@x.com").json()


def test_open_signup_blocked_when_committed_cap_reached(env):
    client, db_session, _ = env
    _admin_token(client)  # 1 registered
    _open_gate(db_session, max_users=2)
    # One outstanding invitation reserves the 2nd (last) seat -> committed == cap.
    from db.models import Invitation
    db = db_session.SessionLocal()
    db.add(Invitation(code="TS-RESV-0001", created_by="admin"))
    db.commit()
    db.close()

    r = _reg(client, "stranger@x.com")
    assert r.status_code == 403
    assert r.json()["detail"] == "REGISTER_CLOSED"


def test_invited_user_bypasses_cap(env):
    client, db_session, _ = env
    _admin_token(client)
    _open_gate(db_session, max_users=1)  # already at cap (admin)
    from db.models import Invitation
    db = db_session.SessionLocal()
    db.add(Invitation(code="TS-GOOD-0001", created_by="admin"))
    db.commit()
    db.close()

    # Invited user is pre-trusted (verified) and bypasses the seat cap.
    r = _reg(client, "invited@x.com", invitation_code="TS-GOOD-0001")
    assert r.status_code == 200
    assert r.json()["email"] == "invited@x.com"
    assert "access_token" in _login(client, "invited@x.com").json()


def test_expired_invitation_rejected(env):
    client, db_session, _ = env
    _admin_token(client)
    from db.models import Invitation
    db = db_session.SessionLocal()
    db.add(Invitation(code="TS-EXPD-0001", created_by="admin",
                      expires_at=datetime.utcnow() - timedelta(days=1)))
    db.commit()
    db.close()
    r = _reg(client, "erin@x.com", invitation_code="TS-EXPD-0001")
    assert r.status_code == 400
    assert r.json()["detail"] == "REGISTER_INVALID_INVITATION"


# --- admin config ----------------------------------------------------------

def test_admin_config_get_patch_and_guards(env):
    client, _, _ = env
    tok = _admin_token(client)
    H = {"Authorization": f"Bearer {tok}"}

    got = client.get("/api/admin/config", headers=H)
    assert got.status_code == 200
    body = got.json()
    assert set(body) == {"registration", "activity", "email_configured"}
    assert body["email_configured"] is True

    patched = client.patch("/api/admin/config", headers=H,
                          json={"registration_open": True, "registration_max_users": 42})
    assert patched.status_code == 200
    assert patched.json()["registration"]["flag_enabled"] is True
    assert patched.json()["registration"]["max_users"] == 42
    assert client.get("/api/public/config").json() == {"registration_open": True}

    # negative cap rejected
    assert client.patch("/api/admin/config", headers=H,
                        json={"registration_max_users": -1}).status_code == 400

    # non-admin blocked: make a verified normal user via an invitation code.
    code = client.post("/api/admin/invitations", headers=H, json={}).json()["code"]
    _reg(client, "normal@x.com", invitation_code=code)
    ntok = _login(client, "normal@x.com").json()["access_token"]
    assert client.get("/api/admin/config",
                      headers={"Authorization": f"Bearer {ntok}"}).status_code == 403


# --- waitlist invite -------------------------------------------------------

def test_waitlist_invite_generates_marks_and_emails(env):
    client, db_session, captured = env
    tok = _admin_token(client)
    H = {"Authorization": f"Bearer {tok}"}

    client.post("/api/auth/waitlist", json={"email": "lead@x.com", "note": "hi", "locale": "zh"})
    wl = client.get("/api/admin/waitlist", headers=H).json()["signups"]
    assert len(wl) == 1 and wl[0]["invited_at"] is None
    assert wl[0]["registered"] is False
    sid = wl[0]["id"]

    res = client.post(f"/api/admin/waitlist/{sid}/invite", headers=H).json()
    assert res["sent"] is True and res["email_configured"] is True
    assert res["code"].startswith("TS-")
    assert any(e["to"] == "lead@x.com" for e in captured["emails"])

    # Row is now marked invited with the issued code.
    wl2 = client.get("/api/admin/waitlist", headers=H).json()["signups"][0]
    assert wl2["invited_at"] is not None
    assert wl2["invitation_code"] == res["code"]

    # The emailed code actually works for registration (invited path).
    r = _reg(client, "lead@x.com", invitation_code=res["code"])
    assert r.status_code == 200

    # Once the lead has an account the row reports registered=True, so the admin
    # UI shows "Joined" and drops the (seat-wasting) Re-invite affordance.
    wl3 = client.get("/api/admin/waitlist", headers=H).json()["signups"][0]
    assert wl3["registered"] is True

    # Re-inviting revokes the previous (now-used) code and issues a new one.
    res2 = client.post(f"/api/admin/waitlist/{sid}/invite", headers=H).json()
    assert res2["code"] != res["code"]


def test_waitlist_registered_flag_ignores_case_and_unrelated(env):
    client, _, _ = env
    tok = _admin_token(client)
    H = {"Authorization": f"Bearer {tok}"}

    # One lead who will register (with different casing), one who won't.
    client.post("/api/auth/waitlist", json={"email": "Mixed.Case@x.com"})
    client.post("/api/auth/waitlist", json={"email": "pending@x.com"})

    code = client.post("/api/admin/invitations", headers=H, json={}).json()["code"]
    assert _reg(client, "mixed.case@x.com", invitation_code=code).status_code == 200

    rows = client.get("/api/admin/waitlist", headers=H).json()["signups"]
    by_email = {r["email"]: r for r in rows}
    assert by_email["Mixed.Case@x.com"]["registered"] is True
    assert by_email["pending@x.com"]["registered"] is False


def test_last_seen_feeds_activity_counts(env):
    client, db_session, _ = env
    tok = _admin_token(client)
    # An authenticated request touches last_seen for the admin.
    client.get("/api/admin/config", headers={"Authorization": f"Bearer {tok}"})
    from api import app_config
    db = db_session.SessionLocal()
    counts = app_config.activity_counts(db)
    db.close()
    assert counts["dau"] >= 1
    assert counts["wau"] >= 1