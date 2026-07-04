"""DB-backed readiness probe /api/health/ready (issue #350).

Mirrors the fresh-DB TestClient setup used by tests/test_version.py.
"""
import pytest


@pytest.fixture
def ready_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "false")
    monkeypatch.setenv(
        "PRAXYS_LOCAL_ENCRYPTION_KEY",
        "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=",
    )
    monkeypatch.delenv("PRAXYS_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)

    from db import session as db_session

    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    from fastapi.testclient import TestClient
    from api.main import app

    return TestClient(app), db_session


def test_health_ready_ok(ready_env):
    client, _ = ready_env
    r = client.get("/api/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "database": "ok"}


def test_health_live_does_not_touch_db(ready_env):
    client, _ = ready_env
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_ready_503_when_db_unavailable(ready_env, monkeypatch):
    client, db_session = ready_env

    class _BrokenSession:
        def execute(self, *args, **kwargs):
            raise RuntimeError("simulated database outage")

        def close(self):
            pass

    monkeypatch.setattr(db_session, "SessionLocal", lambda: _BrokenSession())
    r = client.get("/api/health/ready")
    assert r.status_code == 503
    assert r.json() == {"status": "unavailable", "database": "error"}