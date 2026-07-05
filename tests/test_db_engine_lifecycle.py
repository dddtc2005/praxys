"""Engine lifecycle: idempotent init_db + pool disposal (2026-07-05 outage).

Rebuilding the SQLAlchemy engines on every sync-scheduler tick orphaned a
connection pool each time; combined with pools abandoned on container recycle,
idle "zombie" backends piled up and exhausted the Burstable Postgres server's
small max_connections, 500ing every data endpoint. These tests pin the fix:
init_db() is a no-op once initialized, force=True rebuilds cleanly, and the
dispose helpers release the pools and clear the singletons.
"""
import asyncio

import pytest


@pytest.fixture
def db_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "false")
    monkeypatch.setenv(
        "PRAXYS_LOCAL_ENCRYPTION_KEY",
        "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=",
    )
    monkeypatch.delenv("PRAXYS_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from db import session as db_session

    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()
    try:
        yield db_session
    finally:
        db_session.dispose_engines()


def test_init_db_is_idempotent(db_env):
    db_session = db_env
    first_sync = db_session.engine
    first_async = db_session.async_engine
    first_maker = db_session.SessionLocal

    # Repeated calls (as the sync scheduler does every tick) must NOT rebuild
    # the engines -- rebuilding orphaned a pool each time.
    for _ in range(5):
        db_session.init_db()

    assert db_session.engine is first_sync
    assert db_session.async_engine is first_async
    assert db_session.SessionLocal is first_maker


def test_init_db_force_rebuilds(db_env):
    from sqlalchemy import text

    db_session = db_env
    old_sync = db_session.engine
    old_async = db_session.async_engine

    db_session.init_db(force=True)

    assert db_session.engine is not old_sync
    assert db_session.async_engine is not old_async
    with db_session.engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1


def test_dispose_engines_clears_singletons(db_env):
    db_session = db_env
    assert db_session.engine is not None
    db_session.dispose_engines()
    assert db_session.engine is None
    assert db_session.SessionLocal is None
    assert db_session.async_engine is None
    assert db_session.AsyncSessionLocal is None
    # Safe to call again on already-disposed state.
    db_session.dispose_engines()


def test_dispose_engines_async_clears_singletons(db_env):
    db_session = db_env
    assert db_session.async_engine is not None
    asyncio.run(db_session.dispose_engines_async())
    assert db_session.engine is None
    assert db_session.SessionLocal is None
    assert db_session.async_engine is None
    assert db_session.AsyncSessionLocal is None
