"""Interactive Garmin connect flow with MFA support.

Garmin Connect accounts with multi-factor auth enabled can't be connected
through the lazy background-sync login (garminconnect raises
``GarminConnectAuthenticationError("MFA Required but no prompt_mfa mechanism
supplied")`` because there's no place to prompt for a code in a background
thread). These tests lock down the synchronous connect endpoints that drive
garminconnect's ``return_on_mfa`` / ``resume_login`` handshake so an MFA code
can be entered while the user is present.
"""
import os
import tempfile

import pytest


class _FakeInnerClient:
    """Stand-in for garminconnect's underlying Client — records dump() calls."""

    def __init__(self) -> None:
        self.dumped: list[str] = []

    def dump(self, path: str) -> None:
        self.dumped.append(path)
        # Mirror the real dump: write a token file so the tokenstore exists.
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "garmin_tokens.json"), "w") as f:
            f.write("{}")


def _make_fake_garmin(*, needs_mfa: bool, auth_error: str | None = None):
    """Build a fake ``garminconnect.Garmin`` class + a record of instances."""

    instances: list = []

    class _FakeGarmin:
        def __init__(self, email, password, is_cn=False, return_on_mfa=False, **kw):
            self.email = email
            self.password = password
            self.is_cn = is_cn
            self.return_on_mfa = return_on_mfa
            self.client = _FakeInnerClient()
            self.resume_calls: list[str] = []
            instances.append(self)

        def login(self, tokenstore=None):
            if auth_error is not None:
                from garminconnect import GarminConnectAuthenticationError
                raise GarminConnectAuthenticationError(auth_error)
            if needs_mfa:
                return "needs_mfa", None
            return None, None

        def resume_login(self, client_state, code):
            self.resume_calls.append(code)
            if code != "123456":
                from garminconnect import GarminConnectAuthenticationError
                raise GarminConnectAuthenticationError("Invalid MFA code")
            return None, None

    return _FakeGarmin, instances


@pytest.fixture
def api_client(monkeypatch):
    """TestClient isolated under a temp DB + DATA_DIR, with a seeded user."""
    from fastapi.testclient import TestClient

    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    monkeypatch.setenv("DATA_DIR", tmpdir.name)
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "false")
    monkeypatch.setenv(
        "PRAXYS_LOCAL_ENCRYPTION_KEY", "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o="
    )

    from db import session as db_session
    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    from api.main import app
    from api.auth import get_current_user_id, get_data_user_id, require_write_access
    from db.session import get_db

    test_user_id = "test-user-mfa"

    def _override_current_user():
        return test_user_id

    def _override_db():
        db = db_session.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    from db.models import User
    with db_session.SessionLocal() as db:
        db.add(User(
            id=test_user_id, email="user@test.local",
            hashed_password="x", is_active=True, is_superuser=False,
        ))
        db.commit()

    app.dependency_overrides[get_current_user_id] = _override_current_user
    app.dependency_overrides[get_data_user_id] = _override_current_user
    app.dependency_overrides[require_write_access] = _override_current_user
    app.dependency_overrides[get_db] = _override_db

    # Reset the process-local pending-MFA store between tests.
    from api.routes import sync as sync_mod
    sync_mod._pending_garmin_mfa.clear()

    client = TestClient(app)
    try:
        yield {"client": client, "user_id": test_user_id}
    finally:
        app.dependency_overrides.clear()
        sync_mod._pending_garmin_mfa.clear()
        if db_session.engine is not None:
            db_session.engine.dispose()
        db_session.engine = None
        db_session.SessionLocal = None
        db_session.async_engine = None
        db_session.AsyncSessionLocal = None
        tmpdir.cleanup()


def _connection_status(user_id: str) -> str | None:
    from db import session as db_session
    from db.models import UserConnection
    with db_session.SessionLocal() as db:
        conn = db.query(UserConnection).filter(
            UserConnection.user_id == user_id,
            UserConnection.platform == "garmin",
        ).first()
        return conn.status if conn else None


def test_connect_without_mfa_persists_credentials(api_client, monkeypatch):
    fake, instances = _make_fake_garmin(needs_mfa=False)
    monkeypatch.setattr("garminconnect.Garmin", fake)

    res = api_client["client"].post(
        "/api/settings/connections/garmin/login",
        json={"email": "a@example.com", "password": "pw"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "connected"
    # Credentials stored and tokens dumped for future background syncs.
    assert _connection_status(api_client["user_id"]) == "connected"
    assert instances[0].client.dumped, "tokens should be persisted on success"


def test_connect_requiring_mfa_then_verify(api_client, monkeypatch):
    fake, instances = _make_fake_garmin(needs_mfa=True)
    monkeypatch.setattr("garminconnect.Garmin", fake)

    res = api_client["client"].post(
        "/api/settings/connections/garmin/login",
        json={"email": "a@example.com", "password": "pw", "is_cn": True},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "mfa_required"
    # Nothing persisted until the code is verified.
    assert _connection_status(api_client["user_id"]) is None

    res = api_client["client"].post(
        "/api/settings/connections/garmin/mfa",
        json={"code": "123456"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "connected"
    assert _connection_status(api_client["user_id"]) == "connected"
    assert instances[0].resume_calls == ["123456"]
    assert instances[0].client.dumped, "tokens should be persisted after MFA"


def test_verify_with_wrong_code_keeps_session_for_retry(api_client, monkeypatch):
    fake, instances = _make_fake_garmin(needs_mfa=True)
    monkeypatch.setattr("garminconnect.Garmin", fake)

    api_client["client"].post(
        "/api/settings/connections/garmin/login",
        json={"email": "a@example.com", "password": "pw"},
    )
    bad = api_client["client"].post(
        "/api/settings/connections/garmin/mfa",
        json={"code": "000000"},
    )
    assert bad.status_code == 200
    assert bad.json()["status"] == "error"

    # The pending session survives a wrong code so the user can retry.
    good = api_client["client"].post(
        "/api/settings/connections/garmin/mfa",
        json={"code": "123456"},
    )
    assert good.json()["status"] == "connected"


def test_verify_without_pending_session_reports_expired(api_client):
    res = api_client["client"].post(
        "/api/settings/connections/garmin/mfa",
        json={"code": "123456"},
    )
    assert res.status_code == 200
    assert res.json() == {"status": "error", "message": "mfa_session_expired"}


def test_connect_with_bad_credentials_returns_error(api_client, monkeypatch):
    fake, _ = _make_fake_garmin(needs_mfa=False, auth_error="Invalid Username or Password")
    monkeypatch.setattr("garminconnect.Garmin", fake)

    res = api_client["client"].post(
        "/api/settings/connections/garmin/login",
        json={"email": "a@example.com", "password": "wrong"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "error"
    assert _connection_status(api_client["user_id"]) is None


def test_login_missing_credentials_returns_error(api_client):
    res = api_client["client"].post(
        "/api/settings/connections/garmin/login",
        json={"email": "a@example.com"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "error"


def test_expired_pending_mfa_is_pruned(api_client, monkeypatch):
    fake, _ = _make_fake_garmin(needs_mfa=True)
    monkeypatch.setattr("garminconnect.Garmin", fake)

    api_client["client"].post(
        "/api/settings/connections/garmin/login",
        json={"email": "a@example.com", "password": "pw"},
    )

    from api.routes import sync as sync_mod
    # Age the pending entry past the TTL.
    sync_mod._pending_garmin_mfa[api_client["user_id"]]["created"] -= (
        sync_mod._GARMIN_MFA_TTL_SEC + 1
    )

    res = api_client["client"].post(
        "/api/settings/connections/garmin/mfa",
        json={"code": "123456"},
    )
    assert res.json()["message"] == "mfa_session_expired"
