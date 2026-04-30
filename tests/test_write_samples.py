"""Tests for write_samples() in db/sync_writer.py."""
import tempfile

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
    user_id = "test-user-samples"
    db = db_session.SessionLocal()
    db.add(User(id=user_id, email="samples@example.com", hashed_password="x"))
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


def _make_sample(activity_id: str, t_sec: int, **kwargs) -> dict:
    base = {
        "activity_id": activity_id,
        "source": "stryd",
        "t_sec": t_sec,
        "power_watts": 220.0,
        "hr_bpm": 155.0,
        "speed_ms": 3.5,
        "cadence_spm": 172.0,
        "altitude_m": 50.0,
        "distance_m": float(t_sec) * 3.5,
    }
    base.update(kwargs)
    return base


def test_write_samples_inserts_rows(db_with_user):
    """Basic round-trip: written rows appear in the table with correct values."""
    from db import sync_writer
    from db.models import ActivitySample

    db, user_id = db_with_user
    samples = [_make_sample("act-1", t) for t in range(1000, 1010)]

    count = sync_writer.write_samples(user_id, samples, db)
    db.commit()

    assert count == 10
    rows = db.query(ActivitySample).filter(ActivitySample.activity_id == "act-1").all()
    assert len(rows) == 10
    assert rows[0].power_watts == 220.0
    assert rows[0].hr_bpm == 155.0
    assert rows[0].user_id == user_id


def test_write_samples_idempotent(db_with_user):
    """Writing the same samples twice leaves exactly one copy in the table."""
    from db import sync_writer
    from db.models import ActivitySample

    db, user_id = db_with_user
    samples = [_make_sample("act-2", t) for t in range(2000, 2005)]

    sync_writer.write_samples(user_id, samples, db)
    db.commit()
    sync_writer.write_samples(user_id, samples, db)
    db.commit()

    rows = db.query(ActivitySample).filter(ActivitySample.activity_id == "act-2").all()
    assert len(rows) == 5


def test_write_samples_pace_derived_from_speed(db_with_user):
    """pace_sec_km is computed from speed_ms when not explicitly provided."""
    from db import sync_writer
    from db.models import ActivitySample

    db, user_id = db_with_user
    # 4.0 m/s → 250 sec/km
    samples = [_make_sample("act-3", 3000, speed_ms=4.0, power_watts=None)]

    sync_writer.write_samples(user_id, samples, db)
    db.commit()

    row = db.query(ActivitySample).filter(ActivitySample.activity_id == "act-3").first()
    assert row is not None
    assert row.pace_sec_km == pytest.approx(250.0, rel=1e-3)


def test_write_samples_stryd_dynamics_stored(db_with_user):
    """Stryd-specific running dynamics columns are persisted."""
    from db import sync_writer
    from db.models import ActivitySample

    db, user_id = db_with_user
    samples = [_make_sample(
        "act-4", 4000,
        ground_time_ms=258.0,
        oscillation_mm=71.2,
        leg_spring_kn_m=11.5,
        vertical_ratio=8.3,
        form_power_watts=40.0,
    )]

    sync_writer.write_samples(user_id, samples, db)
    db.commit()

    row = db.query(ActivitySample).filter(ActivitySample.activity_id == "act-4").first()
    assert row.ground_time_ms == 258.0
    assert row.oscillation_mm == 71.2
    assert row.leg_spring_kn_m == 11.5
    assert row.form_power_watts == 40.0


def test_write_samples_skips_rows_missing_t_sec(db_with_user):
    """Rows without t_sec or activity_id are silently dropped."""
    from db import sync_writer
    from db.models import ActivitySample

    db, user_id = db_with_user
    samples = [
        _make_sample("act-5", 5000),
        {"activity_id": "act-5", "source": "stryd", "power_watts": 200.0},  # no t_sec
        {"source": "stryd", "t_sec": 5001, "power_watts": 200.0},           # no activity_id
    ]

    count = sync_writer.write_samples(user_id, samples, db)
    db.commit()

    assert count == 1
    rows = db.query(ActivitySample).filter(ActivitySample.activity_id == "act-5").all()
    assert len(rows) == 1


def test_write_samples_batching(db_with_user):
    """Writing more than _SAMPLE_BATCH_SIZE rows completes correctly."""
    from db import sync_writer
    from db.models import ActivitySample

    db, user_id = db_with_user
    n = sync_writer._SAMPLE_BATCH_SIZE + 50
    samples = [_make_sample("act-6", t) for t in range(6000, 6000 + n)]

    count = sync_writer.write_samples(user_id, samples, db)
    db.commit()

    assert count == n
    total = db.query(ActivitySample).filter(ActivitySample.activity_id == "act-6").count()
    assert total == n


def test_write_samples_empty_input(db_with_user):
    """Empty input returns 0 without error."""
    from db import sync_writer

    db, user_id = db_with_user
    assert sync_writer.write_samples(user_id, [], db) == 0
