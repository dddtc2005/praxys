import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from db.models import Activity, ActivitySplit, Base, FitnessData, RecoveryData, User

FIXTURE_DIR = Path(__file__).parent.parent / "data" / "sample" / "intervals_icu"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(id="u-test", email="t@example.com", hashed_password="x")
        session.add(user)
        session.commit()
        yield session


def _load(name):
    return json.loads((FIXTURE_DIR / name).read_text())


@patch("sync.intervals_icu_sync.fetch_athlete_profile_api")
@patch("sync.intervals_icu_sync.fetch_wellness_api")
@patch("sync.intervals_icu_sync.fetch_activity_laps")
@patch("sync.intervals_icu_sync.fetch_activities_api")
def test_sync_all_writes_all_tables(
    mock_activities, mock_laps, mock_wellness, mock_profile, db
):
    from sync.intervals_icu_sync import (
        _parse_activity, _parse_laps, _parse_wellness, sync_all,
    )

    acts = _load("activities.json")
    mock_activities.return_value = ([_parse_activity(a) for a in acts], acts)
    mock_laps.side_effect = lambda aid, *a, **kw: _parse_laps(
        f"icu_{aid}", _load(f"activity_{aid}_intervals.json"), activity_type="running",
    )
    mock_wellness.return_value = _parse_wellness(_load("wellness.json"))
    mock_profile.return_value = _load("athlete_profile.json")

    credentials = {"athlete_id": "i123456", "api_key": "k"}
    result = sync_all(
        user_id="u-test",
        credentials=credentials,
        db=db,
        since=date(2026, 4, 1),
        today=date(2026, 4, 22),
    )

    assert result.activities_written == 2
    assert result.splits_written == 4  # 3 + 1
    assert result.wellness_written == 5
    assert result.thresholds_written == 4

    activities = db.query(Activity).filter_by(user_id="u-test").all()
    assert {a.activity_id for a in activities} == {"icu_i9000001", "icu_i9000002"}
    assert all(a.source == "intervals_icu" for a in activities)

    splits = db.query(ActivitySplit).filter_by(user_id="u-test").all()
    assert len(splits) == 4

    recovery = db.query(RecoveryData).filter_by(user_id="u-test").all()
    assert len(recovery) == 5
    assert all(r.source == "intervals_icu" for r in recovery)

    fitness = db.query(FitnessData).filter_by(user_id="u-test").all()
    assert {f.metric_type for f in fitness} == {
        "running_ftp", "lthr", "threshold_pace_sec_km", "max_hr",
    }
    assert all(f.source == "intervals_icu" for f in fitness)


@patch("sync.intervals_icu_sync.fetch_athlete_profile_api")
@patch("sync.intervals_icu_sync.fetch_wellness_api")
@patch("sync.intervals_icu_sync.fetch_activity_laps")
@patch("sync.intervals_icu_sync.fetch_activities_api")
def test_sync_all_is_idempotent(
    mock_activities, mock_laps, mock_wellness, mock_profile, db
):
    from sync.intervals_icu_sync import _parse_activity, _parse_laps, _parse_wellness, sync_all

    acts = _load("activities.json")
    mock_activities.return_value = ([_parse_activity(a) for a in acts], acts)
    mock_laps.side_effect = lambda aid, *a, **kw: _parse_laps(
        f"icu_{aid}", _load(f"activity_{aid}_intervals.json"), activity_type="running",
    )
    mock_wellness.return_value = _parse_wellness(_load("wellness.json"))
    mock_profile.return_value = _load("athlete_profile.json")

    credentials = {"athlete_id": "i123456", "api_key": "k"}
    for _ in range(2):
        sync_all(
            user_id="u-test", credentials=credentials, db=db,
            since=date(2026, 4, 1), today=date(2026, 4, 22),
        )

    assert db.query(Activity).filter_by(user_id="u-test").count() == 2
    assert db.query(ActivitySplit).filter_by(user_id="u-test").count() == 4
    assert db.query(RecoveryData).filter_by(user_id="u-test").count() == 5
