"""Regression tests for api.deps._resolve_thresholds.

Guards the Garmin-CN / HR-base user flow: per-activity max_hr is written by
the Garmin sync but no max_hr_bpm fitness_data row is, so the threshold
resolver must fall back to max(Activity.max_hr). Without the fallback HR-base
users end up with thresholds.max_hr_bpm == None, TRIMP returns None, daily
load is 0 everywhere, and the fitness/fatigue chart is empty.
"""
import os
import tempfile
from datetime import date, timedelta

import pytest


@pytest.fixture
def db_with_user(monkeypatch):
    """Yield a Session pointed at a fresh SQLite DB with one test user row."""
    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    monkeypatch.setenv("DATA_DIR", tmpdir.name)
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
    user_id = "test-user-resolve-thresholds"
    db = db_session.SessionLocal()
    db.add(User(id=user_id, email="t@example.com", hashed_password="x"))
    db.commit()

    try:
        yield db, user_id
    finally:
        db.close()
        if db_session.engine is not None:
            db_session.engine.dispose()
        db_session.engine = None
        db_session.SessionLocal = None
        db_session.async_engine = None
        db_session.AsyncSessionLocal = None
        tmpdir.cleanup()


def _fake_config(training_base: str = "hr"):
    """Minimal config stub matching the fields _resolve_thresholds reads."""
    class _C:
        pass
    c = _C()
    c.training_base = training_base
    c.thresholds = {}
    c.connections = {}
    return c


def test_resolve_thresholds_falls_back_to_activity_max_hr(db_with_user):
    """When no fitness_data max_hr_bpm exists, use max(Activity.max_hr)."""
    from db.models import Activity
    from api.deps import _resolve_thresholds

    db, user_id = db_with_user

    today = date.today()
    for i, mh in enumerate([168, 182, 175]):
        db.add(Activity(
            user_id=user_id,
            activity_id=f"act-{i}",
            date=today - timedelta(days=i),
            activity_type="running",
            distance_km=8.0,
            duration_sec=2400.0,
            avg_hr=150.0,
            max_hr=float(mh),
            source="garmin",
        ))
    db.commit()

    result = _resolve_thresholds(_fake_config(), user_id=user_id, db=db)
    assert result.max_hr_bpm == 182.0, (
        "expected max_hr_bpm to fall back to max(Activity.max_hr) when "
        "no fitness_data row exists"
    )


def test_resolve_thresholds_prefers_fitness_data_over_activity_fallback(db_with_user):
    """A fitness_data max_hr_bpm row wins over the Activity fallback."""
    from db.models import Activity, FitnessData
    from api.deps import _resolve_thresholds

    db, user_id = db_with_user

    today = date.today()
    db.add(Activity(
        user_id=user_id, activity_id="a1", date=today,
        activity_type="running", duration_sec=2400.0, max_hr=190.0,
        source="garmin",
    ))
    db.add(FitnessData(
        user_id=user_id, date=today, metric_type="max_hr_bpm",
        value=185.0, source="manual",
    ))
    db.commit()

    result = _resolve_thresholds(_fake_config(), user_id=user_id, db=db)
    assert result.max_hr_bpm == 185.0, (
        "fitness_data entry must take precedence over activity fallback"
    )


def test_resolve_thresholds_manual_override_wins_over_activity_fallback(db_with_user):
    """An explicit config.thresholds override beats every auto-detection path."""
    from db.models import Activity
    from api.deps import _resolve_thresholds

    db, user_id = db_with_user

    today = date.today()
    db.add(Activity(
        user_id=user_id, activity_id="a1", date=today,
        activity_type="running", duration_sec=2400.0, max_hr=190.0,
        source="garmin",
    ))
    db.commit()

    config = _fake_config()
    config.thresholds = {"max_hr_bpm": 195}
    result = _resolve_thresholds(config, user_id=user_id, db=db)
    assert result.max_hr_bpm == 195.0


def test_resolve_thresholds_no_activities_leaves_max_hr_none(db_with_user):
    """No data anywhere — max_hr_bpm stays None rather than raising."""
    from api.deps import _resolve_thresholds

    db, user_id = db_with_user
    result = _resolve_thresholds(_fake_config(), user_id=user_id, db=db)
    assert result.max_hr_bpm is None


def test_write_profile_thresholds_feeds_resolver(db_with_user):
    """Writer populates fitness_data so the resolver surfaces the profile values."""
    from db import sync_writer
    from api.deps import _resolve_thresholds

    db, user_id = db_with_user
    written = sync_writer.write_profile_thresholds(
        user_id, {"max_hr_bpm": 188, "rest_hr_bpm": 48}, db,
    )
    db.commit()
    assert written == 2

    result = _resolve_thresholds(_fake_config(), user_id=user_id, db=db)
    assert result.max_hr_bpm == 188.0
    assert result.rest_hr_bpm == 48.0


