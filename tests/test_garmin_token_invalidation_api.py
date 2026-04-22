"""End-to-end invalidation tests: connect / disconnect / delete_user.

Locks down the contract that every credential-change endpoint clears the
per-user Garmin tokenstore. Regressions here would reproduce the cross-user
leak through a different code path than the original fix.
"""
import os
import tempfile

import pytest


@pytest.fixture
def api_client(monkeypatch):
    """Yield a TestClient + helpers that isolate API under a temp DB + DATA_DIR."""
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

    test_user_id = "test-user-tokens"
    admin_user_id = "test-admin-tokens"

    def _override_current_user():
        return test_user_id

    def _override_admin_user():
        return admin_user_id

    def _override_db():
        db = db_session.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    # Seed both users so role-based endpoints can look them up.
    from db.models import User
    with db_session.SessionLocal() as db:
        db.add(User(
            id=test_user_id, email="user@test.local",
            hashed_password="x", is_active=True, is_superuser=False,
        ))
        db.add(User(
            id=admin_user_id, email="admin@test.local",
            hashed_password="x", is_active=True, is_superuser=True,
        ))
        db.commit()

    app.dependency_overrides[get_current_user_id] = _override_current_user
    app.dependency_overrides[get_data_user_id] = _override_current_user
    app.dependency_overrides[require_write_access] = _override_current_user
    app.dependency_overrides[get_db] = _override_db

    client = TestClient(app)
    try:
        yield {
            "client": client,
            "user_id": test_user_id,
            "admin_id": admin_user_id,
            "override_admin": _override_admin_user,
        }
    finally:
        app.dependency_overrides.clear()
        if db_session.engine is not None:
            db_session.engine.dispose()
        if db_session.async_engine is not None:
            import asyncio
            try:
                asyncio.run(db_session.async_engine.dispose())
            except RuntimeError:
                pass
        db_session.engine = None
        db_session.SessionLocal = None
        db_session.async_engine = None
        db_session.AsyncSessionLocal = None
        tmpdir.cleanup()


def _seed_token_dir(user_id: str) -> str:
    """Drop a dummy tokenstore on disk and return its path."""
    from api.routes.sync import _garmin_token_dir

    path = _garmin_token_dir(user_id)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "oauth2_token.json"), "w") as f:
        f.write("{}")
    assert os.path.isdir(path)
    return path


def test_connect_garmin_clears_existing_tokens(api_client):
    path = _seed_token_dir(api_client["user_id"])
    res = api_client["client"].post(
        "/api/settings/connections/garmin",
        json={"email": "new@example.com", "password": "newpw"},
    )
    assert res.status_code == 200
    assert not os.path.isdir(path)


def test_connect_non_garmin_does_not_touch_garmin_tokens(api_client):
    """Guards against a future invert-the-if regression."""
    path = _seed_token_dir(api_client["user_id"])
    res = api_client["client"].post(
        "/api/settings/connections/oura",
        json={"token": "sk-fake"},
    )
    assert res.status_code == 200
    assert os.path.isdir(path), "Oura connect must not wipe the Garmin tokenstore"


def test_disconnect_garmin_clears_tokens(api_client):
    """Connect first (so there's a DB row to delete), then disconnect."""
    api_client["client"].post(
        "/api/settings/connections/garmin",
        json={"email": "a@example.com", "password": "pw"},
    )
    path = _seed_token_dir(api_client["user_id"])
    res = api_client["client"].delete("/api/settings/connections/garmin")
    assert res.status_code == 200
    assert not os.path.isdir(path)


def test_admin_delete_user_clears_tokens(api_client):
    """Admin deletion is a privacy boundary — cached OAuth tokens must go too."""
    from api.auth import get_current_user_id

    path = _seed_token_dir(api_client["user_id"])
    # Swap in the admin override so the admin route passes _require_admin.
    api_client["client"].app.dependency_overrides[get_current_user_id] = (
        api_client["override_admin"]
    )
    res = api_client["client"].delete(f"/api/admin/users/{api_client['user_id']}")
    assert res.status_code == 200
    assert not os.path.isdir(path)


def test_admin_delete_user_survives_token_cleanup_failure(api_client, monkeypatch):
    """User deletion must succeed even if filesystem cleanup errors — the user
    is already gone from the DB and the endpoint shouldn't 500 the admin."""
    from api.auth import get_current_user_id

    _seed_token_dir(api_client["user_id"])

    def _boom(user_id):
        raise OSError("simulated")

    monkeypatch.setattr("api.routes.sync.clear_garmin_tokens", _boom)

    api_client["client"].app.dependency_overrides[get_current_user_id] = (
        api_client["override_admin"]
    )
    res = api_client["client"].delete(f"/api/admin/users/{api_client['user_id']}")
    assert res.status_code == 200
