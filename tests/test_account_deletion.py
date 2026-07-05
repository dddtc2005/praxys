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
        AppConfig,
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
        WaitlistSignup,
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
        db.add(UserConfig(user_id="demo-user", display_name="Demo"))
        used = Invitation(code="TS-USED-0001", created_by="admin", used_by=user_id, is_active=False)
        made = Invitation(code="TS-MADE-0001", created_by=user_id, is_active=True)
        db.add_all([used, made])
        db.flush()
        # A waitlist lead linked to the invitation the user *created*: it must
        # survive the user's deletion with invitation_id detached (issue #366).
        db.add(WaitlistSignup(email="lead@example.test", invitation_id=made.id))
        # The user last toggled an operator flag; the row must survive with
        # updated_by nulled rather than left dangling (issue #366).
        db.add(AppConfig(key="registration_open", value="true", updated_by=user_id))
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
        AppConfig,
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
        WaitlistSignup,
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

        # The admin-issued invitation the deleted user *used* is preserved as an
        # audit record, but detached (used_by NULL) and deactivated so the freed
        # code cannot be re-claimed (issue #366).
        used_inv = db.query(Invitation).filter(Invitation.code == "TS-USED-0001").one()
        assert used_inv.used_by is None
        assert used_inv.is_active is False

        # The operator-config row the user last touched survives with its
        # reference nulled, not deleted.
        cfg_row = db.query(AppConfig).filter(AppConfig.key == "registration_open").one()
        assert cfg_row.updated_by is None

        # The waitlist lead survives even though the invitation it was linked to
        # (created by the deleted user) is gone — the link is nulled (issue #366).
        lead = db.query(WaitlistSignup).filter(WaitlistSignup.email == "lead@example.test").one()
        assert lead.invitation_id is None

        # Belt-and-braces: nothing anywhere still references a deleted id.
        live_user_ids = {uid for (uid,) in db.query(User.id).all()}
        dangling_user_refs = (
            [r for (r,) in db.query(Invitation.used_by).filter(Invitation.used_by.isnot(None)).all()]
            + [r for (r,) in db.query(Invitation.created_by).all()]
            + [r for (r,) in db.query(AppConfig.updated_by).filter(AppConfig.updated_by.isnot(None)).all()]
        )
        assert all(ref in live_user_ids for ref in dangling_user_refs)
        live_inv_ids = {iid for (iid,) in db.query(Invitation.id).all()}
        waitlist_refs = [
            iid
            for (iid,) in db.query(WaitlistSignup.invitation_id)
            .filter(WaitlistSignup.invitation_id.isnot(None))
            .all()
        ]
        assert all(ref in live_inv_ids for ref in waitlist_refs)
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
def test_delete_user_account_no_dangling_fk_under_enforcement(monkeypatch):
    """Deletion commits under enforced FKs (Postgres-like) with zero orphans.

    Regression for #366: SQLite shipped FK enforcement off, so account deletion
    silently left dangling ``invitations.used_by`` / ``app_config.updated_by`` /
    ``waitlist_signups.invitation_id`` references. With ``PRAGMA foreign_keys=ON``
    those orphans become a hard error at commit, so this proves the deletion path
    clears every reference before dropping the user — exactly the invariant
    PostgreSQL now enforces in production.
    """
    from datetime import date

    from sqlalchemy import create_engine, event
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import api.account_deletion as account_deletion
    from db.models import (
        Activity,
        AppConfig,
        Base,
        Feedback,
        Invitation,
        User,
        UserConfig,
        WaitlistSignup,
    )

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enforce_fks(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    # Mirror production's session config (db/session.py uses autoflush=False) so
    # this stays a faithful proxy for the enforced-FK deletion path.
    Session = sessionmaker(bind=engine, autoflush=False)

    # delete_user_account commits before touching disk tokenstores; stub that
    # step so the test stays DB-only (no DATA_DIR / filesystem dependency).
    monkeypatch.setattr(account_deletion, "_clear_tokenstore", lambda uid: None)

    db = Session()
    try:
        # Seed parents before children so inserts satisfy the enforced FKs: these
        # models use bare ForeignKey columns with no ORM relationship, so the
        # unit of work can't infer insert order (it mirrors the real app, which
        # commits a user at registration before syncing that user's data).
        db.add(User(id="admin", email="admin@x.test", hashed_password="x", is_superuser=True))
        db.add(User(id="target", email="t@x.test", hashed_password="x"))
        db.commit()
        db.add(User(id="target-demo", email="d@x.test", hashed_password="x", is_demo=True, demo_of="target"))
        db.commit()
        db.add(UserConfig(user_id="target", display_name="T"))
        db.add(Activity(user_id="target", activity_id="a1", date=date(2026, 6, 1)))
        db.add(Feedback(user_id="target", kind="bug", message="hi", status="new"))
        made = Invitation(code="TS-MADE-9999", created_by="target", is_active=True)
        used = Invitation(code="TS-USED-9999", created_by="admin", used_by="target", is_active=True)
        db.add_all([made, used])
        db.commit()
        db.add(WaitlistSignup(email="w1@x.test", invitation_id=made.id))
        db.add(AppConfig(key="registration_open", value="true", updated_by="target"))
        db.commit()
    finally:
        db.close()

    db = Session()
    try:
        result = account_deletion.delete_user_account(db, "target", enforce_last_admin_guard=False)
    finally:
        db.close()

    assert set(result.deleted_user_ids) == {"target", "target-demo"}

    db = Session()
    try:
        assert db.query(User).filter(User.id.in_(["target", "target-demo"])).count() == 0
        # Invitation the user *used* is preserved, detached, and deactivated.
        used_row = db.query(Invitation).filter(Invitation.code == "TS-USED-9999").one()
        assert used_row.used_by is None
        assert used_row.is_active is False
        # Invitation the user *created* is deleted (created_by is NOT NULL).
        assert db.query(Invitation).filter(Invitation.code == "TS-MADE-9999").count() == 0
        # Waitlist lead kept with its (now-deleted) invitation link nulled.
        wl = db.query(WaitlistSignup).filter(WaitlistSignup.email == "w1@x.test").one()
        assert wl.invitation_id is None
        # Operator-config row kept, updated_by nulled.
        cfg = db.query(AppConfig).filter(AppConfig.key == "registration_open").one()
        assert cfg.updated_by is None
    finally:
        db.close()
    engine.dispose()
