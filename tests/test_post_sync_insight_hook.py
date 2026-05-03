"""Integration tests for the post-sync LLM insight hook.

The runner has its own unit tests; here we verify the *wiring* — that
``_run_sync`` (api/routes/sync.py) and ``_sync_connection`` (db/sync_scheduler.py)
both invoke ``run_insights_for_user`` with the correct ``counts`` and that a
runner failure can never break the surrounding sync.

We mock the platform fetch + DB writer at the function level so this stays
self-contained: the test is about hook wiring, not actual sync data.
"""
from __future__ import annotations

import tempfile
from datetime import date, timedelta

import pytest


@pytest.fixture
def sync_setup(monkeypatch):
    """Init DB + seed a user for the sync hook tests."""
    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    monkeypatch.setenv("DATA_DIR", tmpdir.name)
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "false")
    monkeypatch.setenv(
        "PRAXYS_LOCAL_ENCRYPTION_KEY",
        "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=",
    )

    from db import session as db_session
    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    from db.models import User

    user_id = "post-sync-hook-user"
    db = db_session.SessionLocal()
    try:
        db.add(User(id=user_id, email="hook@example.com", hashed_password="x"))
        db.commit()
    finally:
        db.close()

    yield user_id, tmpdir


def test_run_sync_invokes_insight_runner_with_counts(sync_setup, monkeypatch):
    """When sync writes new rows, the post-sync hook fires with those counts."""
    user_id, _ = sync_setup
    captured: dict = {}

    def _fake_sync_garmin(user_id, creds, from_date, db):
        return {"activities": 3, "splits": 12}

    def _fake_run_insights(uid, db, counts):
        captured["user_id"] = uid
        captured["counts"] = dict(counts)
        return {"daily_brief": "generated"}

    from api.routes import sync as sync_module
    monkeypatch.setattr(sync_module, "_sync_garmin", _fake_sync_garmin)
    monkeypatch.setattr(
        "api.insights_runner.run_insights_for_user", _fake_run_insights
    )

    sync_module._run_sync(user_id, "garmin", {"email": "e", "password": "p"})

    assert captured["user_id"] == user_id
    assert captured["counts"] == {"activities": 3, "splits": 12}


def test_run_sync_completes_when_insight_runner_raises(sync_setup, monkeypatch):
    """A runner exception must not break the surrounding sync — status stays
    'done', the connection's last_sync still updates, no insight rows leak."""
    user_id, _ = sync_setup

    def _fake_sync_garmin(user_id, creds, from_date, db):
        return {"activities": 1, "splits": 4}

    def _exploding_runner(*args, **kwargs):
        raise RuntimeError("simulated LLM tier failure")

    from api.routes import sync as sync_module
    from db.models import AiInsight, UserConnection
    from db.session import SessionLocal

    # Pre-create a connection so _run_sync's last_sync update has a target.
    db = SessionLocal()
    try:
        db.add(UserConnection(
            user_id=user_id, platform="garmin",
            encrypted_credentials=b"x", wrapped_dek=b"x",
            status="syncing",
        ))
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(sync_module, "_sync_garmin", _fake_sync_garmin)
    monkeypatch.setattr(
        "api.insights_runner.run_insights_for_user", _exploding_runner
    )

    # Should NOT raise.
    sync_module._run_sync(user_id, "garmin", {"email": "e", "password": "p"})

    # Sync state must reflect a successful sync despite the hook explosion.
    db = SessionLocal()
    try:
        conn = db.query(UserConnection).filter(
            UserConnection.user_id == user_id,
            UserConnection.platform == "garmin",
        ).one()
        assert conn.status == "connected"
        assert conn.last_sync is not None

        # Runner exploded → no AiInsight rows written.
        assert db.query(AiInsight).filter_by(user_id=user_id).count() == 0
    finally:
        db.close()
