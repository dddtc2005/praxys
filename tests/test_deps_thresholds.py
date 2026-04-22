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


def _fake_config(
    training_base: str = "hr",
    activity_source: str | None = None,
    threshold_sources: dict | None = None,
):
    """Minimal config stub matching the fields _resolve_thresholds reads."""
    class _C:
        pass
    c = _C()
    c.training_base = training_base
    c.thresholds = {}
    c.connections = {}
    c.preferences = {}
    if activity_source:
        c.preferences["activities"] = activity_source
    if threshold_sources:
        c.preferences["threshold_sources"] = threshold_sources
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


def test_resolve_thresholds_ignores_legacy_manual_values(db_with_user):
    """Regression for the clean-break migration: legacy manual values in
    ``config.thresholds`` are no longer applied. Every threshold must come
    from a sensor row or a calculation on the user's own data.
    """
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
    # Simulate a user who previously entered 195 as a manual override.
    # The resolver should ignore this and use the activity fallback (190).
    config.thresholds = {"max_hr_bpm": 195, "cp_watts": 999, "lthr_bpm": 999}
    result = _resolve_thresholds(config, user_id=user_id, db=db)
    assert result.max_hr_bpm == 190.0, "activity fallback should win over legacy manual value"
    assert result.cp_watts is None, "legacy manual cp_watts must be ignored"
    assert result.lthr_bpm is None, "legacy manual lthr_bpm must be ignored"


def test_resolve_thresholds_picks_preferred_source_when_multiple_present(db_with_user):
    """When both Stryd and Garmin write cp_estimate, the explicit
    threshold_sources preference wins over the latest-by-date default."""
    from db.models import FitnessData
    from api.deps import _resolve_thresholds

    db, user_id = db_with_user
    today = date.today()
    # Garmin's cp_estimate is newer by date.
    db.add(FitnessData(
        user_id=user_id, date=today, metric_type="cp_estimate",
        value=350.0, source="garmin",
    ))
    db.add(FitnessData(
        user_id=user_id, date=today - timedelta(days=3), metric_type="cp_estimate",
        value=265.0, source="stryd",
    ))
    db.commit()

    # Without preference: latest-by-date wins (Garmin 350).
    result = _resolve_thresholds(_fake_config(), user_id=user_id, db=db)
    assert result.cp_watts == 350.0

    # With explicit Stryd preference: stale Stryd value wins over fresh Garmin.
    cfg = _fake_config(threshold_sources={"cp_estimate": "stryd"})
    result = _resolve_thresholds(cfg, user_id=user_id, db=db)
    assert result.cp_watts == 265.0

    # Default to activity source: preferences.activities == "stryd" picks Stryd.
    cfg = _fake_config(activity_source="stryd")
    result = _resolve_thresholds(cfg, user_id=user_id, db=db)
    assert result.cp_watts == 265.0

    # Explicit threshold_sources overrides the activity-source default.
    cfg = _fake_config(
        activity_source="stryd",
        threshold_sources={"cp_estimate": "garmin"},
    )
    result = _resolve_thresholds(cfg, user_id=user_id, db=db)
    assert result.cp_watts == 350.0


def test_resolve_thresholds_falls_back_when_preferred_source_has_no_data(db_with_user):
    """If the preferred source never wrote a row, fall back to the latest
    from any source rather than returning None."""
    from db.models import FitnessData
    from api.deps import _resolve_thresholds

    db, user_id = db_with_user
    db.add(FitnessData(
        user_id=user_id, date=date.today(), metric_type="cp_estimate",
        value=265.0, source="stryd",
    ))
    db.commit()

    # Prefer Garmin, but Garmin never wrote — fall back to Stryd.
    cfg = _fake_config(threshold_sources={"cp_estimate": "garmin"})
    result = _resolve_thresholds(cfg, user_id=user_id, db=db)
    assert result.cp_watts == 265.0


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


def test_write_profile_thresholds_upserts_existing_same_day(db_with_user):
    """A second write on the same day updates in place rather than duplicating.

    Guards the UPDATE filter (user_id + date + metric_type) against future
    refactors that might drop a predicate and silently overwrite the wrong
    row or create a duplicate.
    """
    from db import sync_writer
    from db.models import FitnessData
    from api.deps import _resolve_thresholds

    db, user_id = db_with_user

    sync_writer.write_profile_thresholds(
        user_id, {"max_hr_bpm": 185, "rest_hr_bpm": 50}, db,
    )
    db.commit()
    sync_writer.write_profile_thresholds(
        user_id, {"max_hr_bpm": 188, "rest_hr_bpm": 48}, db,
    )
    db.commit()

    rows = db.query(FitnessData).filter(
        FitnessData.user_id == user_id,
        FitnessData.metric_type.in_(("max_hr_bpm", "rest_hr_bpm")),
    ).all()
    assert len(rows) == 2, "Second write must update existing rows, not append"

    result = _resolve_thresholds(_fake_config(), user_id=user_id, db=db)
    assert result.max_hr_bpm == 188.0
    assert result.rest_hr_bpm == 48.0


def test_hr_base_daily_load_non_zero_via_trimp_fallback(db_with_user):
    """End-to-end regression: an HR-base user with max_hr_bpm and activities
    but no lthr_bpm (the Garmin CN shape) must still get non-zero daily load.

    Before the fix, thresholds.max_hr_bpm was always None because the Garmin
    sync never wrote it, compute_activity_load returned None for the HR
    branch, the cross-base TRIMP fallback also required max_hr_bpm, and every
    daily load collapsed to 0 — empty fitness/fatigue chart. This test would
    have failed on main.
    """
    import pandas as pd
    from db.models import Activity
    from api.deps import _resolve_thresholds, _compute_daily_load

    db, user_id = db_with_user
    today = date.today()
    for i in range(3):
        db.add(Activity(
            user_id=user_id,
            activity_id=f"a{i}",
            date=today - timedelta(days=i),
            activity_type="running",
            distance_km=10.0,
            duration_sec=3000.0,
            avg_hr=150.0,
            max_hr=178.0,
            source="garmin",
        ))
    db.commit()

    config = _fake_config(training_base="hr")
    thresholds = _resolve_thresholds(config, user_id=user_id, db=db)

    # max_hr_bpm must come from the Activity fallback (no fitness_data row).
    assert thresholds.max_hr_bpm == 178.0
    assert thresholds.lthr_bpm is None

    activities_df = pd.DataFrame([
        {
            "date": today - timedelta(days=i),
            "duration_sec": 3000.0,
            "avg_hr": 150.0,
            "distance_km": 10.0,
        }
        for i in range(3)
    ])
    date_range = pd.date_range(today - timedelta(days=2), today)
    daily_load = _compute_daily_load(activities_df, date_range, config, thresholds)
    assert daily_load.sum() > 0, (
        "HR-base daily load must be non-zero via cross-base TRIMP when "
        "max_hr_bpm is resolved, even without lthr_bpm"
    )


