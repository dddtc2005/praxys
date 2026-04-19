"""Integration tests for the /api/settings PUT endpoint validation.

Covers the scheduler-interval validation wired in api/routes/settings.py:
the unit-level normalize is tested in test_sync_scheduler.py; this file
proves the API translates a ValueError into a structured 400 response and
that the settings GET surfaces the allowed-options contract the UI depends on.
"""
import os
import tempfile

import pytest


@pytest.fixture
def api_client(monkeypatch):
    """Yield a FastAPI TestClient pointing at a fresh, isolated SQLite DB."""
    from fastapi.testclient import TestClient

    # ignore_cleanup_errors lets Windows clean up even if SQLite hasn't
    # released the file lock by the time the temp dir is removed.
    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    monkeypatch.setenv("DATA_DIR", tmpdir.name)
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "false")
    monkeypatch.setenv(
        "PRAXYS_LOCAL_ENCRYPTION_KEY", "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o="
    )
    # Reset the module-level engine singletons so init_db rebuilds against tmpdir.
    from db import session as db_session
    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    from api.main import app
    from api.auth import require_write_access, get_data_user_id
    from db.session import get_db

    test_user_id = "test-user-settings-api"

    def _override_user():
        return test_user_id

    def _override_db():
        db = db_session.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[require_write_access] = _override_user
    app.dependency_overrides[get_data_user_id] = _override_user
    app.dependency_overrides[get_db] = _override_db

    client = TestClient(app)
    try:
        yield client, test_user_id
    finally:
        app.dependency_overrides.clear()
        # Dispose engines so SQLite releases the file before tmpdir cleanup
        # (Windows can't unlink a file held by an open connection pool).
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


def test_put_settings_rejects_invalid_sync_interval(api_client):
    """An invalid sync_interval_hours must return 400 with the validator's message."""
    client, _ = api_client
    res = client.put("/api/settings", json={"source_options": {"sync_interval_hours": 3}})
    assert res.status_code == 400, res.text
    detail = res.json().get("detail", "")
    assert "interval" in detail.lower()
    assert "(6, 12, 24)" in detail


def test_put_settings_accepts_allowed_sync_interval(api_client):
    """An allowed sync_interval_hours must persist and round-trip via GET."""
    client, _ = api_client
    res = client.put("/api/settings", json={"source_options": {"sync_interval_hours": 12}})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ok"
    assert body["config"]["source_options"]["sync_interval_hours"] == 12

    got = client.get("/api/settings")
    assert got.status_code == 200, got.text
    got_body = got.json()
    assert got_body["config"]["source_options"]["sync_interval_hours"] == 12


def test_get_settings_exposes_sync_interval_options(api_client):
    """GET /api/settings must expose the option list the Settings UI dropdown consumes."""
    client, _ = api_client
    res = client.get("/api/settings")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sync_interval_options_hours"] == [6, 12, 24]
    assert body["default_sync_interval_hours"] == 6
