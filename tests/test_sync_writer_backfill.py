"""Regression tests for fill-only upserts in write_activities / write_splits.

Covers the re-sync case: a user who already synced activities under an older
parser that didn't read native Garmin running power needs those rows topped
up on re-sync, but fields already populated (e.g. Stryd power on a dual-sync
activity) must not be overwritten.
"""
import tempfile
from datetime import date, timedelta

import pytest


@pytest.fixture
def db_with_user(monkeypatch):
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
    user_id = "test-user-writer-backfill"
    db = db_session.SessionLocal()
    db.add(User(id=user_id, email="w@example.com", hashed_password="x"))
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


def test_write_activities_backfills_native_power_on_existing_row(db_with_user):
    """Re-syncing an old activity with power now in the payload fills the column."""
    from db import sync_writer
    from db.models import Activity

    db, user_id = db_with_user
    today = date.today()

    sync_writer.write_activities(user_id, [{
        "activity_id": "act-1",
        "date": today.isoformat(),
        "duration_sec": "3000",
        "avg_hr": "150",
        "max_hr": "180",
        # old parser emitted no power fields
    }], db)
    db.commit()

    count = sync_writer.write_activities(user_id, [{
        "activity_id": "act-1",
        "date": today.isoformat(),
        "duration_sec": "3000",
        "avg_hr": "150",
        "max_hr": "180",
        "avg_power": "252.4",
        "max_power": "410.0",
    }], db)
    db.commit()

    assert count == 1, "Fill should count as one touched row"
    row = db.query(Activity).filter(Activity.activity_id == "act-1").one()
    assert row.avg_power == 252.4
    assert row.max_power == 410.0


def test_write_activities_never_overwrites_existing_power(db_with_user):
    """An existing non-null power value wins over a fresh parse."""
    from db import sync_writer
    from db.models import Activity

    db, user_id = db_with_user
    today = date.today()

    sync_writer.write_activities(user_id, [{
        "activity_id": "act-1",
        "date": today.isoformat(),
        "duration_sec": "3000",
        "avg_power": "280.0",  # Stryd-sourced, say
    }], db)
    db.commit()

    sync_writer.write_activities(user_id, [{
        "activity_id": "act-1",
        "date": today.isoformat(),
        "duration_sec": "3000",
        "avg_power": "252.4",  # Garmin native power — must not clobber Stryd
    }], db)
    db.commit()

    row = db.query(Activity).filter(Activity.activity_id == "act-1").one()
    assert row.avg_power == 280.0, (
        "Existing non-null power must survive a re-sync with a different value"
    )


def test_write_splits_backfills_native_power(db_with_user):
    """A split that was stored without power gets filled on re-sync."""
    from db import sync_writer
    from db.models import ActivitySplit

    db, user_id = db_with_user

    sync_writer.write_splits(user_id, [{
        "activity_id": "act-1",
        "split_num": "1",
        "distance_km": "1.0",
        "duration_sec": "300",
        "avg_hr": "150",
    }], db)
    db.commit()

    count = sync_writer.write_splits(user_id, [{
        "activity_id": "act-1",
        "split_num": "1",
        "distance_km": "1.0",
        "duration_sec": "300",
        "avg_hr": "150",
        "avg_power": "245",
    }], db)
    db.commit()

    assert count == 1
    split = db.query(ActivitySplit).filter(
        ActivitySplit.activity_id == "act-1",
        ActivitySplit.split_num == 1,
    ).one()
    assert split.avg_power == 245.0


def test_write_splits_preserves_existing_ciq_power(db_with_user):
    """Stryd ConnectIQ power from the first sync must not be overwritten."""
    from db import sync_writer
    from db.models import ActivitySplit

    db, user_id = db_with_user

    sync_writer.write_splits(user_id, [{
        "activity_id": "act-1", "split_num": "1",
        "distance_km": "1.0", "duration_sec": "300",
        "avg_power": "270",  # old CIQ read
    }], db)
    db.commit()

    sync_writer.write_splits(user_id, [{
        "activity_id": "act-1", "split_num": "1",
        "distance_km": "1.0", "duration_sec": "300",
        "avg_power": "240",  # new native read — different value
    }], db)
    db.commit()

    split = db.query(ActivitySplit).filter(
        ActivitySplit.activity_id == "act-1",
        ActivitySplit.split_num == 1,
    ).one()
    assert split.avg_power == 270.0


def test_write_activities_new_row_still_inserts(db_with_user):
    """Baseline: a never-before-seen activity still gets inserted."""
    from db import sync_writer
    from db.models import Activity

    db, user_id = db_with_user
    today = date.today()

    count = sync_writer.write_activities(user_id, [{
        "activity_id": "act-new",
        "date": today.isoformat(),
        "duration_sec": "3000",
        "avg_hr": "150",
        "avg_power": "250.0",
    }], db)
    db.commit()

    assert count == 1
    row = db.query(Activity).filter(Activity.activity_id == "act-new").one()
    assert row.avg_power == 250.0


def test_write_activities_nothing_to_fill_returns_zero(db_with_user):
    """If the existing row already has all fill columns populated, no touch, no count."""
    from db import sync_writer

    db, user_id = db_with_user
    today = date.today()

    sync_writer.write_activities(user_id, [{
        "activity_id": "act-1",
        "date": today.isoformat(),
        "duration_sec": "3000",
        "avg_power": "250.0",
        "max_power": "400.0",
    }], db)
    db.commit()

    count = sync_writer.write_activities(user_id, [{
        "activity_id": "act-1",
        "date": today.isoformat(),
        "duration_sec": "3000",
        "avg_power": "250.0",
        "max_power": "400.0",
    }], db)
    db.commit()

    assert count == 0


# ---------------------------------------------------------------------------
# Oura recovery upserts
# ---------------------------------------------------------------------------


def _readiness_row(d: date, score: int = 80) -> dict:
    return {"date": d.isoformat(), "readiness_score": str(score),
            "hrv_avg": "", "resting_hr": "",
            "body_temperature_delta": "0.1"}


def _sleep_row(d: date, sleep_score: int = 75) -> dict:
    return {"date": d.isoformat(), "sleep_score": str(sleep_score),
            "total_sleep_sec": "28800", "deep_sleep_sec": "7200",
            "rem_sleep_sec": "5400", "light_sleep_sec": "16200",
            "efficiency": "92"}


def test_write_recovery_oura_backfills_null_hrv_on_existing_row(db_with_user):
    """Re-syncing fills HRV/RHR on rows previously inserted with nulls.

    This is the production bug: rows landed without HRV (e.g., before the
    extraction logic was correct, or due to a multi-record day overwriting
    the long_sleep entry), and the dedup on existing date prevented any
    later sync from filling them. The recovery analysis stayed stuck on
    "insufficient HRV data" forever.
    """
    from db import sync_writer
    from db.models import RecoveryData

    db, user_id = db_with_user
    today = date.today()

    # First sync: HRV missing (mirrors a buggy / partial sleep response)
    sync_writer.write_recovery(
        user_id,
        readiness_rows=[_readiness_row(today)],
        sleep_rows=[_sleep_row(today)],
        hrv_by_date={},
        db=db,
    )
    db.commit()

    row = db.query(RecoveryData).filter(
        RecoveryData.user_id == user_id, RecoveryData.source == "oura",
    ).one()
    assert row.hrv_avg is None
    assert row.resting_hr is None

    # Second sync: same date, but now HRV/RHR are present
    count = sync_writer.write_recovery(
        user_id,
        readiness_rows=[_readiness_row(today)],
        sleep_rows=[_sleep_row(today)],
        hrv_by_date={today.isoformat(): {"hrv_avg": "45.5", "resting_hr": "52"}},
        db=db,
    )
    db.commit()

    assert count == 1, "Backfill should count as one touched row"
    row = db.query(RecoveryData).filter(
        RecoveryData.user_id == user_id, RecoveryData.source == "oura",
    ).one()
    assert row.hrv_avg == 45.5
    assert row.resting_hr == 52.0


def test_write_recovery_oura_does_not_overwrite_existing_hrv(db_with_user):
    """A re-sync must not clobber an HRV value already in the DB.

    Existing valid bio fields are authoritative; Oura is the source of
    truth and we only fill gaps, never overwrite.
    """
    from db import sync_writer
    from db.models import RecoveryData

    db, user_id = db_with_user
    today = date.today()

    sync_writer.write_recovery(
        user_id,
        readiness_rows=[_readiness_row(today)],
        sleep_rows=[_sleep_row(today)],
        hrv_by_date={today.isoformat(): {"hrv_avg": "50.0", "resting_hr": "55"}},
        db=db,
    )
    db.commit()

    sync_writer.write_recovery(
        user_id,
        readiness_rows=[_readiness_row(today)],
        sleep_rows=[_sleep_row(today)],
        hrv_by_date={today.isoformat(): {"hrv_avg": "30.0", "resting_hr": "70"}},
        db=db,
    )
    db.commit()

    row = db.query(RecoveryData).filter(
        RecoveryData.user_id == user_id, RecoveryData.source == "oura",
    ).one()
    assert row.hrv_avg == 50.0, "Existing HRV must survive re-sync"
    assert row.resting_hr == 55.0


def test_write_recovery_oura_new_date_still_inserts(db_with_user):
    """Baseline: a never-before-seen Oura date still gets inserted."""
    from db import sync_writer
    from db.models import RecoveryData

    db, user_id = db_with_user
    today = date.today()

    count = sync_writer.write_recovery(
        user_id,
        readiness_rows=[_readiness_row(today)],
        sleep_rows=[_sleep_row(today)],
        hrv_by_date={today.isoformat(): {"hrv_avg": "40.0", "resting_hr": "58"}},
        db=db,
    )
    db.commit()

    assert count == 1
    row = db.query(RecoveryData).filter(
        RecoveryData.user_id == user_id, RecoveryData.source == "oura",
    ).one()
    assert row.hrv_avg == 40.0
    assert row.resting_hr == 58.0
    assert row.sleep_score == 75.0


def test_write_recovery_oura_skips_when_existing_complete(db_with_user):
    """No-op re-sync (same data) returns zero touches."""
    from db import sync_writer

    db, user_id = db_with_user
    today = date.today()
    payload = dict(
        readiness_rows=[_readiness_row(today)],
        sleep_rows=[_sleep_row(today)],
        hrv_by_date={today.isoformat(): {"hrv_avg": "45.0", "resting_hr": "55"}},
    )

    sync_writer.write_recovery(user_id, db=db, **payload)
    db.commit()

    count = sync_writer.write_recovery(user_id, db=db, **payload)
    db.commit()
    assert count == 0
