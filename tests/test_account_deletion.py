"""Tests for self-service account deletion."""
from __future__ import annotations

import importlib
import tempfile
from datetime import date

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def account_client(monkeypatch):
    """Yield a TestClient backed by a fresh SQLite DB and overridable user id."""
    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    monkeypatch.setenv("DATA_DIR", tmpdir.name)
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "false")
    monkeypatch.setenv(
        "PRAXYS_LOCAL_ENCRYPTION_KEY",
        "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=",
    )
    monkeypatch.setenv("PRAXYS_AUTH_RATE_LIMIT_DISABLED", "true")

    from db import session as db_session

    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    import api.main

    importlib.reload(api.main)
    app = api.main.app

    current_user_id = {"value": "delete-me"}

    def _override_user() -> str:
        return current_user_id["value"]

    def _override_db():
        db = db_session.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    from fastapi import HTTPException
    from api.auth import get_current_user_id, require_write_access
    from db.models import User
    from db.session import get_db

    def _override_write_access() -> str:
        db = db_session.SessionLocal()
        try:
            user = db.query(User).filter(User.id == current_user_id["value"]).first()
            if user and user.is_demo:
                raise HTTPException(403, "Demo accounts cannot modify data")
            return current_user_id["value"]
        finally:
            db.close()

    app.dependency_overrides[get_current_user_id] = _override_user
    app.dependency_overrides[require_write_access] = _override_write_access
    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)
    client.current_user_id = current_user_id  # type: ignore[attr-defined]
    try:
        yield client, db_session
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


def _seed_account_rows(db_session, user_id: str = "delete-me") -> None:
    """Insert one row in every user-owned table account deletion must purge."""
    from db.models import (
        Activity,
        ActivitySample,
        ActivitySplit,
        AiInsight,
        CacheRevision,
        DashboardCache,
        Feedback,
        FitnessData,
        Invitation,
        RecoveryData,
        TrainingPlan,
        User,
        UserConfig,
        UserConnection,
    )

    db = db_session.SessionLocal()
    try:
        admin = User(id="admin", email="admin@example.test", hashed_password="x", is_superuser=True)
        user = User(
            id=user_id,
            email="athlete@example.test",
            hashed_password="x",
            wechat_openid="openid-delete-me",
        )
        demo = User(id="demo-user", email="demo@example.test", hashed_password="x", is_demo=True, demo_of=user_id)
        db.add_all([admin, user, demo])
        db.add(UserConfig(user_id=user_id, display_name="Delete Me"))
        db.add(UserConnection(user_id=user_id, platform="garmin", encrypted_credentials=b"secret"))
        db.add(Activity(user_id=user_id, activity_id="a1", date=date(2026, 6, 1)))
        db.add(ActivitySplit(user_id=user_id, activity_id="a1", split_num=1))
        db.add(ActivitySample(user_id=user_id, activity_id="a1", source="garmin", t_sec=1))
        db.add(RecoveryData(user_id=user_id, date=date(2026, 6, 1), source="oura"))
        db.add(FitnessData(user_id=user_id, date=date(2026, 6, 1), metric_type="cp_estimate", value=300))
        db.add(TrainingPlan(user_id=user_id, date=date(2026, 6, 2), source="ai", workout_type="easy"))
        db.add(AiInsight(user_id=user_id, insight_type="daily_brief"))
        db.add(CacheRevision(user_id=user_id, scope="activities", revision=1))
        db.add(DashboardCache(user_id=user_id, section="today", source_version="v1", payload_json=b"{}"))
        db.add(Feedback(user_id=user_id, kind="bug", message="delete me", status="new"))
        db.add(Invitation(code="TS-USED-0001", created_by="admin", used_by=user_id, is_active=False))
        db.add(Invitation(code="TS-MADE-0001", created_by=user_id, is_active=True))
        db.add(UserConfig(user_id="demo-user", display_name="Demo"))
        db.commit()
    finally:
        db.close()


def test_delete_me_removes_user_and_owned_rows(account_client):
    """DELETE /api/me hard-deletes account data, credentials, demo, and invitation links."""
    client, db_session = account_client
    _seed_account_rows(db_session)

    res = client.delete("/api/me")
    assert res.status_code == 200, res.text
    assert res.json() == {"status": "deleted", "email": "athlete@example.test"}

    from db.models import (
        Activity,
        ActivitySample,
        ActivitySplit,
        AiInsight,
        CacheRevision,
        DashboardCache,
        Feedback,
        FitnessData,
        Invitation,
        RecoveryData,
        TrainingPlan,
        User,
        UserConfig,
        UserConnection,
    )

    db = db_session.SessionLocal()
    try:
        assert db.query(User).filter(User.id.in_(["delete-me", "demo-user"])).count() == 0
        for model in (
            Activity,
            ActivitySample,
            ActivitySplit,
            AiInsight,
            CacheRevision,
            DashboardCache,
            Feedback,
            FitnessData,
            RecoveryData,
            TrainingPlan,
            UserConfig,
            UserConnection,
        ):
            assert db.query(model).filter(model.user_id.in_(["delete-me", "demo-user"])).count() == 0
        assert db.query(Invitation).filter(
            (Invitation.used_by == "delete-me") | (Invitation.created_by == "delete-me")
        ).count() == 0
    finally:
        db.close()


def test_delete_me_rejects_last_admin(account_client):
    """The only admin cannot delete their own account and strand the app adminless."""
    client, db_session = account_client
    client.current_user_id["value"] = "solo-admin"  # type: ignore[attr-defined]

    from db.models import User

    db = db_session.SessionLocal()
    try:
        db.add(User(id="solo-admin", email="admin@example.test", hashed_password="x", is_superuser=True))
        db.commit()
    finally:
        db.close()

    res = client.delete("/api/me")
    assert res.status_code == 400, res.text
    assert res.json()["detail"] == "LAST_ADMIN_CANNOT_DELETE_ACCOUNT"

    db = db_session.SessionLocal()
    try:
        assert db.query(User).filter(User.id == "solo-admin").count() == 1
    finally:
        db.close()

def test_delete_me_rejects_demo_account(account_client):
    """Demo users stay read-only and cannot self-delete the shared demo account."""
    client, db_session = account_client
    client.current_user_id["value"] = "demo-only"  # type: ignore[attr-defined]

    from db.models import User

    db = db_session.SessionLocal()
    try:
        db.add(User(id="admin", email="admin@example.test", hashed_password="x", is_superuser=True))
        db.add(User(id="demo-only", email="demo@example.test", hashed_password="x", is_demo=True, demo_of="admin"))
        db.commit()
    finally:
        db.close()

    res = client.delete("/api/me")
    assert res.status_code == 403, res.text
    assert res.json()["detail"] == "Demo accounts cannot modify data"

    db = db_session.SessionLocal()
    try:
        assert db.query(User).filter(User.id == "demo-only").count() == 1
    finally:
        db.close()

def test_run_sync_rolls_back_if_user_deactivated_before_commit(account_client, monkeypatch):
    """An in-flight sync must not commit orphaned rows after deletion starts."""
    _, db_session = account_client

    from datetime import date

    from api.routes import sync as sync_routes
    from db.models import Activity, User, UserConnection

    db = db_session.SessionLocal()
    try:
        db.add(User(id="sync-user", email="sync@example.test", hashed_password="x", is_active=True))
        db.add(UserConnection(user_id="sync-user", platform="garmin", status="connected", consecutive_failures=0))
        db.commit()
    finally:
        db.close()

    def _fake_sync(user_id: str, creds: dict, from_date: str | None, db) -> dict:
        db.add(Activity(user_id=user_id, activity_id="orphan-candidate", date=date(2026, 6, 30)))
        other = db_session.SessionLocal()
        try:
            user = other.query(User).filter(User.id == user_id).one()
            user.is_active = False
            other.commit()
        finally:
            other.close()
        return {"activities": 1}

    monkeypatch.setattr(sync_routes, "_sync_garmin", _fake_sync)
    sync_routes._run_sync("sync-user", "garmin", {}, None)

    db = db_session.SessionLocal()
    try:
        assert db.query(Activity).filter(Activity.activity_id == "orphan-candidate").count() == 0
        assert db.query(User).filter(User.id == "sync-user", User.is_active == False).count() == 1  # noqa: E712
        conn = db.query(UserConnection).filter(UserConnection.user_id == "sync-user").one()
        assert conn.status == "connected"
        assert conn.consecutive_failures == 0
    finally:
        db.close()
