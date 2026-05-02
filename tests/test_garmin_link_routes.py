"""Smoke tests for the interactive Garmin login routes.

Full end-to-end testing requires Chromium and a live Garmin account, both
of which are out of scope for unit tests. This file covers the wiring
that doesn't depend on either:

* Routes register and serve auth-required responses.
* Session lifecycle (start → look up → cancel) updates state correctly
  without ever launching Chromium (we monkey-patch the worker thread).
* Token persistence writes to the per-user tokenstore and resets the
  connection's backoff state — the contract the regular sync path
  expects.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def app_with_user(monkeypatch):
    """Spin a FastAPI test client + seed an authed user.

    Mirrors the pattern in test_post_sync_insight_hook so we don't drag
    in extra fixtures.
    """
    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    monkeypatch.setenv("DATA_DIR", tmpdir.name)
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "false")
    monkeypatch.setenv(
        "PRAXYS_LOCAL_ENCRYPTION_KEY",
        "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=",
    )
    monkeypatch.setenv("PRAXYS_JWT_SECRET", "test-secret-32-chars-long-aaaaaaaa")
    monkeypatch.setenv("PRAXYS_AUTH_RATE_LIMIT_DISABLED", "1")

    from db import session as db_session
    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    from db.models import User
    user_id = "interactive-test-user"
    db = db_session.SessionLocal()
    try:
        db.add(User(id=user_id, email="link@example.com", hashed_password="x"))
        db.commit()
    finally:
        db.close()

    # Build a JWT the routes accept.
    import jwt as jwt_lib
    from datetime import datetime, timedelta, timezone
    token = jwt_lib.encode(
        {
            "sub": user_id,
            "aud": "fastapi-users:auth",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        "test-secret-32-chars-long-aaaaaaaa",
        algorithm="HS256",
    )

    from fastapi.testclient import TestClient
    from api.main import app
    client = TestClient(app)

    yield client, user_id, token, tmpdir


# ---------------------------------------------------------------------------
# Auth gates
# ---------------------------------------------------------------------------

def test_start_interactive_requires_auth(app_with_user):
    client, _, _, _ = app_with_user
    res = client.post(
        "/api/settings/connections/garmin/interactive",
        json={"email": "x@y.com", "password": "p", "is_cn": False},
    )
    assert res.status_code == 401


def test_get_session_requires_auth(app_with_user):
    client, _, _, _ = app_with_user
    res = client.get(
        "/api/settings/connections/garmin/interactive/nonexistent",
    )
    assert res.status_code == 401


def test_get_session_404_for_unknown_id(app_with_user):
    client, _, token, _ = app_with_user
    res = client.get(
        "/api/settings/connections/garmin/interactive/does-not-exist",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 404


def test_get_session_403_when_session_belongs_to_other_user(app_with_user):
    """An attacker who learns a session_id must not be able to read it."""
    client, user_id, token, _ = app_with_user
    from api.routes.garmin_link import _Session, _sessions, _sessions_lock

    with _sessions_lock:
        sess = _Session(
            id="hijack-target",
            user_id="some-other-user",
            email="x@y.com", password="p", is_cn=False,
        )
        _sessions[sess.id] = sess

    res = client.get(
        f"/api/settings/connections/garmin/interactive/{sess.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Session validation
# ---------------------------------------------------------------------------

def test_start_interactive_rejects_empty_credentials(app_with_user):
    client, _, token, _ = app_with_user
    res = client.post(
        "/api/settings/connections/garmin/interactive",
        json={"email": "", "password": "p", "is_cn": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 400


def test_start_interactive_creates_session_and_skips_chromium_in_test(
    app_with_user, monkeypatch,
):
    """Don't launch Chromium during tests — we just verify the API stub
    that creates the session, queues the worker, and returns the id."""
    client, user_id, token, _ = app_with_user

    # Skip the real install + worker; the latter would launch Playwright
    # which the test environment doesn't have set up. Replacing the
    # worker function (rather than monkey-patching Thread.start globally)
    # keeps SQLAlchemy / scheduler / azure-monitor threads functional.
    from api.routes import garmin_link
    monkeypatch.setattr(garmin_link, "_ensure_chromium_installed", lambda: None)
    started = []

    def _fake_worker(sess):
        started.append(sess.id)
        sess.state = "ready"
    monkeypatch.setattr(garmin_link, "_run_browser_session", _fake_worker)

    res = client.post(
        "/api/settings/connections/garmin/interactive",
        json={"email": "user@example.com", "password": "secret", "is_cn": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["session_id"]
    # Worker thread runs the fake _run_browser_session which records
    # the session id; allow a moment for the daemon thread to schedule.
    import time
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and not started:
        time.sleep(0.05)
    assert started, "Browser worker thread was not started"

    # The session row must be visible to the same user via the GET endpoint.
    sid = body["session_id"]
    res = client.get(
        f"/api/settings/connections/garmin/interactive/{sid}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["session_id"] == sid
    assert payload["state"] in ("starting", "ready", "failed", "closed")
    assert payload["viewport"] == {"width": 1024, "height": 768}


# ---------------------------------------------------------------------------
# Token persistence
# ---------------------------------------------------------------------------

def test_persist_uses_submitted_credentials_over_original_post(
    app_with_user, monkeypatch,
):
    """When the user corrects a typo in the relayed viewport, the
    final password is what Garmin actually accepts. The Playwright
    request listener captures it into ``submitted_email`` /
    ``submitted_password``, and persistence must prefer those over
    the original /interactive POST values — otherwise we'd encrypt a
    known-stale password and silently break refresh-expiry password
    auth ~30 days later.
    """
    client, user_id, _, _ = app_with_user
    from api.routes.garmin_link import _Session, _persist_captured_tokens
    from api.routes.sync import _garmin_token_dir
    from db import session as db_session
    from db.models import UserConnection
    from db.crypto import get_vault

    sess = _Session(
        id="typo-corrected",
        user_id=user_id,
        email="user@old-typo.com",
        password="WRONG_PASSWORD",
        is_cn=False,
    )
    sess.captured_tokens = {
        "di_token": "fake.di",
        "di_refresh_token": "fake.refresh",
        "di_client_id": "GARMIN_CONNECT_MOBILE_ANDROID_DI_2025Q2",
    }
    # The Playwright request listener saw the user submit the corrected
    # values, which are what Garmin's auth backend accepted.
    sess.submitted_email = "user@correct.com"
    sess.submitted_password = "RIGHT_PASSWORD"

    _persist_captured_tokens(sess)

    db = db_session.SessionLocal()
    try:
        conn = db.query(UserConnection).filter(
            UserConnection.user_id == user_id,
            UserConnection.platform == "garmin",
        ).first()
        decrypted = get_vault().decrypt(
            conn.encrypted_credentials, conn.wrapped_dek,
        )
        creds = json.loads(decrypted)
        assert creds["email"] == "user@correct.com", (
            "Submitted email must override the /interactive POST value"
        )
        assert creds["password"] == "RIGHT_PASSWORD", (
            "Submitted password must override the /interactive POST value — "
            "otherwise refresh-expiry password auth would loop on the wrong "
            "password until the user reconnects again."
        )
    finally:
        db.close()


def test_persist_captured_tokens_writes_tokenstore_and_resets_backoff(
    app_with_user, monkeypatch,
):
    """The success path must:
    1. Write garmin_tokens.json at the per-user path the regular sync
       reads from.
    2. Store creds in the encrypted connection blob so refresh-token
       expiry can fall back to password auth (which the backoff state
       machine handles if it CAPTCHA-fails again).
    3. Reset consecutive_failures / next_retry_at / last_error so the
       scheduler resumes the platform on the next tick.
    """
    client, user_id, _token, _ = app_with_user
    from api.routes.garmin_link import _Session, _persist_captured_tokens
    from api.routes.sync import _garmin_token_dir
    from db import session as db_session
    from db.models import UserConnection

    # Pre-create a connection in error state with backoff bumped — this
    # is the realistic scenario where the user resorts to interactive
    # login after the regular flow flagged auth_required.
    db = db_session.SessionLocal()
    try:
        db.add(UserConnection(
            user_id=user_id,
            platform="garmin",
            status="auth_required",
            consecutive_failures=4,
            last_error="GarminConnectConnectionError: CAPTCHA_REQUIRED",
        ))
        db.commit()
    finally:
        db.close()

    sess = _Session(
        id="persist-test",
        user_id=user_id,
        email="user@example.com",
        password="secret",
        is_cn=False,
    )
    sess.captured_tokens = {
        "di_token": "fake.di.token",
        "di_refresh_token": "fake.refresh.token",
        "di_client_id": "GARMIN_CONNECT_MOBILE_ANDROID_DI_2025Q2",
    }

    _persist_captured_tokens(sess)

    # 1. Token file landed where the regular sync reads it.
    token_path = Path(_garmin_token_dir(user_id)) / "garmin_tokens.json"
    assert token_path.exists()
    on_disk = json.loads(token_path.read_text())
    assert on_disk["di_token"] == "fake.di.token"
    assert on_disk["di_refresh_token"] == "fake.refresh.token"

    # 2. + 3. Connection state reset.
    db = db_session.SessionLocal()
    try:
        conn = db.query(UserConnection).filter(
            UserConnection.user_id == user_id,
            UserConnection.platform == "garmin",
        ).first()
        assert conn is not None
        assert conn.status == "connected"
        assert conn.consecutive_failures == 0
        assert conn.next_retry_at is None
        assert conn.last_error is None
        assert conn.encrypted_credentials is not None  # creds persisted
    finally:
        db.close()
