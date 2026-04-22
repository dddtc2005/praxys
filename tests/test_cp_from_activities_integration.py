"""End-to-end test for activity-derived CP.

Verifies the contract between:

  db.sync_writer.update_cp_from_activities
      → analysis.cp_from_activities.estimate_cp_from_activities
          → db.models.ActivitySplit / Activity
      → db.models.FitnessData row (source="activities")
  api.deps._resolve_thresholds (picks it up when user selects that source)

Uses the same ``db_with_user`` fixture pattern as
``tests/test_deps_thresholds.py`` so the sqlite layer is real.
"""
import tempfile
from datetime import date, timedelta

import pytest

from analysis.cp_from_activities import MIN_FIT_POINTS


@pytest.fixture
def db_with_user(monkeypatch):
    """Fresh SQLite DB with one test user row."""
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
    user_id = "test-user-cp-from-activities"
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


def _seed_cp_friendly_activities(db, user_id: str, cp: float, wp: float) -> None:
    """Seed activities + splits whose best-efforts imply ``cp`` / ``wp``.

    One activity per bin of the fit window (3, 5, 10, 20 min). Splits inside
    each activity carry the bin's peak (duration, power) so
    ``collect_mean_max_points`` will hand those pairs to the fit.
    """
    from db.models import Activity, ActivitySplit

    today = date(2026, 4, 22)
    efforts = [
        (180.0, cp + wp / 180.0),
        (300.0, cp + wp / 300.0),
        (600.0, cp + wp / 600.0),
        (1200.0, cp + wp / 1200.0),
    ]
    for i, (duration, power) in enumerate(efforts):
        activity_id = f"act-{i}"
        db.add(Activity(
            user_id=user_id,
            activity_id=activity_id,
            date=today - timedelta(days=i * 3),  # spread within lookback
            activity_type="running",
            distance_km=duration / 240.0,  # nominal 4:00/km pace, not load-bearing
            duration_sec=duration,
            avg_power=power,
            source="garmin",
        ))
        db.add(ActivitySplit(
            user_id=user_id,
            activity_id=activity_id,
            split_num=1,
            duration_sec=duration,
            avg_power=power,
        ))
    db.commit()


def test_writer_persists_fit_row(db_with_user):
    """A clean fit produces one FitnessData row with source='activities'."""
    from db.sync_writer import update_cp_from_activities
    from db.models import FitnessData

    db, user_id = db_with_user
    _seed_cp_friendly_activities(db, user_id, cp=260.0, wp=15_000.0)

    fit = update_cp_from_activities(
        user_id, db, lookback_days=60, today=date(2026, 4, 22),
    )
    db.commit()

    assert fit is not None, "expected a fit from 4 CP-consistent efforts"
    # Recovered CP should be very close to the seeded truth.
    assert abs(fit["cp_watts"] - 260.0) < 1.0

    rows = db.query(FitnessData).filter(
        FitnessData.user_id == user_id,
        FitnessData.metric_type == "cp_estimate",
        FitnessData.source == "activities",
    ).all()
    assert len(rows) == 1, "exactly one activities-sourced CP row expected"
    assert abs(rows[0].value - 260.0) < 1.0
    assert rows[0].date == date(2026, 4, 22)


def test_writer_upserts_same_day(db_with_user):
    """Running the writer twice on the same day updates in place."""
    from db.sync_writer import update_cp_from_activities
    from db.models import FitnessData

    db, user_id = db_with_user
    _seed_cp_friendly_activities(db, user_id, cp=260.0, wp=15_000.0)

    update_cp_from_activities(user_id, db, lookback_days=60, today=date(2026, 4, 22))
    db.commit()
    update_cp_from_activities(user_id, db, lookback_days=60, today=date(2026, 4, 22))
    db.commit()

    rows = db.query(FitnessData).filter(
        FitnessData.user_id == user_id,
        FitnessData.metric_type == "cp_estimate",
        FitnessData.source == "activities",
    ).all()
    assert len(rows) == 1, "same-day re-run must upsert, not duplicate"


def test_writer_returns_none_and_keeps_existing_row_when_fit_fails(db_with_user):
    """An earlier good fit stays put if the next attempt can't fit.

    Scenario: user had a good CP estimate last week, then took a week of
    easy jogs — no hard efforts to fit. The previous row should NOT be
    deleted; the UI shows the last known good CP with its stale date.
    """
    from db.sync_writer import update_cp_from_activities
    from db.models import FitnessData

    db, user_id = db_with_user
    _seed_cp_friendly_activities(db, user_id, cp=260.0, wp=15_000.0)
    update_cp_from_activities(user_id, db, lookback_days=60, today=date(2026, 4, 22))
    db.commit()

    # Delete the seeded splits so the next fit has nothing to work with.
    from db.models import ActivitySplit
    db.query(ActivitySplit).filter(ActivitySplit.user_id == user_id).delete()
    from db.models import Activity
    db.query(Activity).filter(Activity.user_id == user_id).delete()
    db.commit()

    fit = update_cp_from_activities(user_id, db, lookback_days=60, today=date(2026, 4, 23))
    db.commit()
    assert fit is None, "no activities → no fit"

    # Previous row still present and unchanged.
    rows = db.query(FitnessData).filter(
        FitnessData.user_id == user_id,
        FitnessData.metric_type == "cp_estimate",
        FitnessData.source == "activities",
    ).all()
    assert len(rows) == 1
    assert abs(rows[0].value - 260.0) < 1.0
    assert rows[0].date == date(2026, 4, 22), "old row's as_of must be preserved"


def test_writer_does_not_touch_other_source_rows(db_with_user):
    """Writing the activities row must leave Garmin/Stryd rows alone."""
    from db.sync_writer import update_cp_from_activities
    from db.models import FitnessData

    db, user_id = db_with_user
    _seed_cp_friendly_activities(db, user_id, cp=260.0, wp=15_000.0)

    # Pre-seed a Garmin-native and Stryd row for the same day + metric.
    when = date(2026, 4, 22)
    db.add(FitnessData(
        user_id=user_id, date=when, metric_type="cp_estimate",
        source="garmin", value=340.0,
    ))
    db.add(FitnessData(
        user_id=user_id, date=when, metric_type="cp_estimate",
        source="stryd", value=258.0,
    ))
    db.commit()

    update_cp_from_activities(user_id, db, lookback_days=60, today=when)
    db.commit()

    rows = db.query(FitnessData).filter(
        FitnessData.user_id == user_id,
        FitnessData.metric_type == "cp_estimate",
    ).all()
    by_source = {r.source: r.value for r in rows}
    assert len(rows) == 3, "expected garmin, stryd, and activities rows to coexist"
    assert by_source["garmin"] == 340.0
    assert by_source["stryd"] == 258.0
    assert abs(by_source["activities"] - 260.0) < 1.0


def test_resolve_thresholds_picks_activities_when_preferred(db_with_user):
    """When user chooses 'activities' in Settings, _resolve_thresholds picks it.

    This is the whole point of the feature — give the user a CP that
    matches their actual activity power, and make it pickable in the UI.
    """
    from db.sync_writer import update_cp_from_activities
    from db.models import FitnessData
    from api.deps import _resolve_thresholds

    db, user_id = db_with_user
    _seed_cp_friendly_activities(db, user_id, cp=260.0, wp=15_000.0)

    # Garmin's inflated FTP is the ONLY other CP source — the exact
    # mismatch scenario the feature targets.
    db.add(FitnessData(
        user_id=user_id, date=date(2026, 4, 22), metric_type="cp_estimate",
        source="garmin", value=340.0,
    ))
    db.commit()

    update_cp_from_activities(user_id, db, lookback_days=60, today=date(2026, 4, 22))
    db.commit()

    class _Config:
        training_base = "power"
        thresholds: dict = {}
        connections: dict = {}
        preferences: dict = {"threshold_sources": {"cp_estimate": "activities"}}

    resolved = _resolve_thresholds(_Config(), user_id=user_id, db=db)
    assert resolved.cp_watts is not None
    assert abs(resolved.cp_watts - 260.0) < 1.0, (
        "with the activities preference the resolver must NOT fall through "
        "to Garmin's 340W — that's the Scenario-3 bug this feature fixes"
    )


def test_min_fit_points_constant_used_by_integration():
    """Guard: if someone relaxes MIN_FIT_POINTS below 3, the integration
    test fixture (which seeds 4 efforts) must still cover it with headroom.
    """
    assert MIN_FIT_POINTS <= 4
