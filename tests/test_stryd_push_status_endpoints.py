"""Endpoint-level tests for Stryd push-status isolation.

Helper-level tests (tests/test_stryd_push_status_isolation.py) prove that
_load_push_status/_save_push_status scope by user_id correctly. These
tests additionally prove the three plan.py endpoints thread the calling
user's user_id into those helpers — if a refactor dropped user_id at any
call site, the helper unit tests would keep passing and the regression
would slip through.
"""
import os
import tempfile
from unittest.mock import MagicMock

import pandas as pd
import pytest


@pytest.fixture
def api_client(monkeypatch, tmp_path):
    """TestClient with a temp DATA_DIR and overridable 'current user'."""
    from fastapi.testclient import TestClient

    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    monkeypatch.setenv("DATA_DIR", tmpdir.name)
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "false")
    monkeypatch.setenv(
        "PRAXYS_LOCAL_ENCRYPTION_KEY", "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o="
    )
    monkeypatch.setenv("PRAXYS_JWT_SECRET", "test-secret-endpoint-push-status")

    from db import session as db_session
    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    # Point the plan module's _STRYD_PUSH_STATUS_DIR into the scratch dir too.
    from api.routes import plan as plan_mod
    scratch_root = os.path.join(tmpdir.name, "ai", "stryd_push_status")
    monkeypatch.setattr(plan_mod, "_DATA_DIR", tmpdir.name)
    monkeypatch.setattr(plan_mod, "_STRYD_PUSH_STATUS_DIR", scratch_root)

    from api.main import app
    from api.auth import get_current_user_id, get_data_user_id, require_write_access
    from db.session import get_db

    current_user_id = {"value": "alice"}

    def _override_current_user():
        return current_user_id["value"]

    def _override_db():
        db = db_session.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_current_user_id] = _override_current_user
    app.dependency_overrides[get_data_user_id] = _override_current_user
    app.dependency_overrides[require_write_access] = _override_current_user
    app.dependency_overrides[get_db] = _override_db

    client = TestClient(app)
    try:
        yield {"client": client, "current": current_user_id}
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


def test_get_status_returns_only_current_users_data(api_client):
    """The original regression: user B's GET must not surface user A's writes."""
    from api.routes.plan import _save_push_status

    _save_push_status("alice", {"2026-05-01": {"workout_id": "alice-only"}})
    _save_push_status("bob", {"2026-06-15": {"workout_id": "bob-only"}})

    api_client["current"]["value"] = "bob"
    res = api_client["client"].get("/api/plan/stryd-status")
    assert res.status_code == 200
    assert res.json() == {"2026-06-15": {"workout_id": "bob-only"}}

    api_client["current"]["value"] = "alice"
    res = api_client["client"].get("/api/plan/stryd-status")
    assert res.json() == {"2026-05-01": {"workout_id": "alice-only"}}


def test_push_endpoint_persists_under_calling_user(api_client, monkeypatch):
    """POST /plan/push-stryd must write to the caller's file, not a shared one."""
    monkeypatch.setenv("STRYD_EMAIL", "stub@example.com")
    monkeypatch.setenv("STRYD_PASSWORD", "stub")
    monkeypatch.setattr(
        "sync.stryd_sync._login_api", lambda e, p: ("stryd-user-id", "fake-token"),
    )
    monkeypatch.setattr(
        "sync.stryd_sync.build_workout_blocks", lambda workout, cp: [],
    )
    monkeypatch.setattr(
        "sync.stryd_sync.create_workout_api",
        lambda **kwargs: {"id": f"new-workout-for-{kwargs.get('workout_date')}"},
    )

    plan_df = pd.DataFrame([
        {
            "date": "2026-05-07",
            "workout_type": "easy_run",
            "planned_duration_min": 45,
            "workout_description": "Aerobic easy effort",
            "target_power_min": 200, "target_power_max": 230,
        },
    ])
    # plan.py imported get_dashboard_data by name, so patch the local binding.
    monkeypatch.setattr(
        "api.routes.plan.get_dashboard_data",
        lambda user_id, db: {
            "plan": plan_df, "latest_cp": 260.0, "activities": pd.DataFrame(),
            "signal": {}, "training_base": "power",
        },
    )

    api_client["current"]["value"] = "carol"
    res = api_client["client"].post(
        "/api/plan/push-stryd",
        json={"workout_dates": ["2026-05-07"]},
    )
    assert res.status_code == 200, res.text

    from api.routes.plan import _load_push_status
    # Carol's file got the update.
    carol_status = _load_push_status("carol")
    assert "2026-05-07" in carol_status
    assert carol_status["2026-05-07"]["workout_id"] == "new-workout-for-2026-05-07"
    # Alice's file (previously empty) is untouched — no leak.
    assert _load_push_status("alice") == {}


def test_delete_endpoint_touches_only_calling_users_status(api_client, monkeypatch):
    """DELETE /plan/stryd-workout/{id} must not remove entries from another user's status."""
    from api.routes.plan import _save_push_status, _load_push_status

    # Two users pushed the same Stryd workout_id (hypothetically — unusual, but
    # if it happened, deleting as one user must not scrub the other's record).
    _save_push_status("alice", {"2026-05-01": {"workout_id": "shared-id"}})
    _save_push_status("bob", {"2026-05-01": {"workout_id": "shared-id"}})

    monkeypatch.setenv("STRYD_EMAIL", "stub@example.com")
    monkeypatch.setenv("STRYD_PASSWORD", "stub")
    monkeypatch.setattr(
        "sync.stryd_sync._login_api", lambda e, p: ("stryd-user-id", "fake-token"),
    )
    monkeypatch.setattr("sync.stryd_sync.delete_workout_api", lambda *a, **kw: None)

    api_client["current"]["value"] = "bob"
    res = api_client["client"].delete("/api/plan/stryd-workout/shared-id")
    assert res.status_code == 200

    # Bob's record is gone...
    assert _load_push_status("bob") == {}
    # ...but Alice's is preserved.
    assert _load_push_status("alice") == {"2026-05-01": {"workout_id": "shared-id"}}
