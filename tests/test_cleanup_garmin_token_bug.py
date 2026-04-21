"""Tests for scripts/cleanup_garmin_token_bug.py.

The script is a one-shot, destructive operation. The dangerous properties to
lock down:
 - never deletes rows belonging to any admin user,
 - preserves non-Garmin sources (Stryd splits, Oura recovery),
 - refuses to run when no admin exists (otherwise a missing admin flag would
   cause the script to wipe every user's Garmin data).
"""
from datetime import date

import pytest


@pytest.fixture
def seeded_db(tmp_path, monkeypatch):
    """Yield a session against a temp SQLite DB with admin + non-admin users."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv(
        "PRAXYS_LOCAL_ENCRYPTION_KEY", "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o="
    )

    from db import session as db_session
    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    from db.models import (
        Activity, ActivitySplit, FitnessData, User, UserConnection,
    )

    admin_id = "admin-1"
    user_id = "user-1"

    with db_session.SessionLocal() as db:
        db.add(User(id=admin_id, email="admin@x", hashed_password="x",
                    is_active=True, is_superuser=True))
        db.add(User(id=user_id, email="u1@x", hashed_password="x",
                    is_active=True, is_superuser=False))
        # Shared activity_id across admin + non-admin — this is the pathological
        # case: the non-admin's Garmin rows carry the admin's activity_id.
        shared_id = "shared-act-42"
        db.add(Activity(user_id=admin_id, activity_id=shared_id,
                        date=date(2026, 4, 1), source="garmin"))
        db.add(Activity(user_id=user_id, activity_id=shared_id,
                        date=date(2026, 4, 1), source="garmin"))
        # Admin also has a Stryd activity that must survive the cleanup.
        db.add(Activity(user_id=admin_id, activity_id="stryd-1",
                        date=date(2026, 4, 2), source="stryd"))
        # Splits: one row per user against the shared activity_id.
        db.add(ActivitySplit(user_id=admin_id, activity_id=shared_id, split_num=1))
        db.add(ActivitySplit(user_id=user_id, activity_id=shared_id, split_num=1))
        # Fitness data: both users have Garmin VO2max, only non-admin's should go.
        db.add(FitnessData(user_id=admin_id, date=date(2026, 4, 1),
                           metric_type="vo2max", value=55.0, source="garmin"))
        db.add(FitnessData(user_id=user_id, date=date(2026, 4, 1),
                           metric_type="vo2max", value=55.0, source="garmin"))
        # Non-admin Garmin connection — should get last_sync=NULL after apply.
        db.add(UserConnection(user_id=user_id, platform="garmin",
                              status="connected"))
        db.commit()

    try:
        yield db_session
    finally:
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


def test_apply_preserves_admin_rows_across_all_tables(seeded_db):
    """Admin's activities, splits, AND fitness rows must survive _apply()."""
    from db.models import Activity, ActivitySplit, FitnessData
    from scripts.cleanup_garmin_token_bug import _apply

    admin_id = "admin-1"
    user_id = "user-1"

    with seeded_db.SessionLocal() as db:
        result = _apply(db, [admin_id])

    with seeded_db.SessionLocal() as db:
        # Admin side — nothing lost.
        assert db.query(Activity).filter(
            Activity.user_id == admin_id, Activity.source == "garmin",
        ).count() == 1, "admin Garmin activity must survive"
        assert db.query(ActivitySplit).filter(
            ActivitySplit.user_id == admin_id,
        ).count() == 1, "admin splits must survive (this was the reviewed bug)"
        assert db.query(FitnessData).filter(
            FitnessData.user_id == admin_id,
        ).count() == 1, "admin Garmin fitness row must survive"
        # Admin's Stryd row is also untouched.
        assert db.query(Activity).filter(
            Activity.user_id == admin_id, Activity.source == "stryd",
        ).count() == 1

        # Non-admin side — everything Garmin is gone.
        assert db.query(Activity).filter(
            Activity.user_id == user_id, Activity.source == "garmin",
        ).count() == 0
        assert db.query(ActivitySplit).filter(
            ActivitySplit.user_id == user_id,
        ).count() == 0
        assert db.query(FitnessData).filter(
            FitnessData.user_id == user_id, FitnessData.source == "garmin",
        ).count() == 0

    assert result["activities_deleted"] == 1
    assert result["splits_deleted"] == 1
    assert result["fitness_deleted"] == 1
    assert result["connections_reset"] == 1


def test_apply_is_idempotent(seeded_db):
    """Second run should delete zero additional rows and not raise."""
    from scripts.cleanup_garmin_token_bug import _apply

    with seeded_db.SessionLocal() as db:
        _apply(db, ["admin-1"])

    with seeded_db.SessionLocal() as db:
        result = _apply(db, ["admin-1"])

    assert result == {
        "activities_deleted": 0,
        "splits_deleted": 0,
        "fitness_deleted": 0,
        # last_sync is already NULL from the first run, but the UPDATE still
        # matches the row — so connections_reset may be 1 again. We only
        # require no data loss.
        "connections_reset": result["connections_reset"],
    }


def test_main_aborts_when_no_admin_exists(seeded_db, monkeypatch):
    """Without this guard an admin-less DB would have EVERY Garmin row wiped."""
    from db.models import User, Activity
    from scripts import cleanup_garmin_token_bug

    # Strip admin status from the seeded admin.
    with seeded_db.SessionLocal() as db:
        admin = db.query(User).filter(User.id == "admin-1").first()
        admin.is_superuser = False
        db.commit()

    # Argv patched so argparse sees --apply (the dangerous path).
    monkeypatch.setattr("sys.argv", ["cleanup_garmin_token_bug.py", "--apply"])

    exit_code = cleanup_garmin_token_bug.main()
    assert exit_code == 2

    # No rows were deleted.
    with seeded_db.SessionLocal() as db:
        assert db.query(Activity).filter(
            Activity.source == "garmin",
        ).count() == 2, "abort path must not delete any rows"
