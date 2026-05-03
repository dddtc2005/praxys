"""Tests for /api/auth/waitlist — the private-alpha lead-capture endpoint.

The waitlist sits under /api/auth/* so it inherits the same rate-limit
middleware that protects login + register; the smoke is here, the limiter's
own behavior is exercised in test_auth_rate_limit*.py.
"""
from __future__ import annotations

import importlib
import tempfile

import pytest
from fastapi.testclient import TestClient


def _build_app(monkeypatch, data_dir: str):
    monkeypatch.setenv("DATA_DIR", data_dir)
    monkeypatch.setenv("TRAINSIGHT_SYNC_SCHEDULER", "false")
    monkeypatch.setenv(
        "TRAINSIGHT_LOCAL_ENCRYPTION_KEY",
        "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=",
    )
    monkeypatch.setenv("PRAXYS_AUTH_RATE_LIMIT_DISABLED", "true")
    monkeypatch.delenv("WECHAT_MINIAPP_APPID", raising=False)
    monkeypatch.delenv("WECHAT_MINIAPP_SECRET", raising=False)

    from db import session as db_session

    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    import api.users
    import api.invitations

    importlib.reload(api.users)
    importlib.reload(api.invitations)

    import api.main

    importlib.reload(api.main)
    return api.main.app, db_session


@pytest.fixture
def app_client(monkeypatch):
    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    try:
        app, db_session = _build_app(monkeypatch, tmpdir.name)
        with TestClient(app) as client:
            yield client, db_session
    finally:
        try:
            if db_session.engine is not None:
                db_session.engine.dispose()
        except Exception:
            pass
        try:
            tmpdir.cleanup()
        except Exception:
            pass


def test_waitlist_creates_signup(app_client):
    client, _ = app_client
    r = client.post(
        "/api/auth/waitlist",
        json={"email": "runner@example.com", "note": "sub-3 marathon", "locale": "en"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "status": "created"}


def test_waitlist_idempotent_on_email(app_client):
    """Re-submitting the same email refreshes rather than creating a duplicate."""
    client, db_session = app_client

    r1 = client.post("/api/auth/waitlist", json={"email": "dup@example.com"})
    assert r1.json()["status"] == "created"

    r2 = client.post(
        "/api/auth/waitlist",
        json={"email": "dup@example.com", "note": "updated goal"},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "refreshed"

    from db.models import WaitlistSignup

    with db_session.SessionLocal() as s:
        rows = s.query(WaitlistSignup).filter_by(email="dup@example.com").all()
        assert len(rows) == 1
        assert rows[0].note == "updated goal"


def test_waitlist_rejects_malformed_email(app_client):
    client, _ = app_client
    r = client.post("/api/auth/waitlist", json={"email": "not-an-email"})
    assert r.status_code == 422  # pydantic EmailStr rejects


def test_waitlist_truncates_long_note(app_client):
    """Pydantic Field max_length=500 rejects oversized notes rather than silently truncating."""
    client, _ = app_client
    r = client.post(
        "/api/auth/waitlist",
        json={"email": "long@example.com", "note": "x" * 501},
    )
    assert r.status_code == 422
