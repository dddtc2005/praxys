import os
import tempfile
import pandas as pd
import pytest
from analysis.data_loader import load_all_data, match_activities, discover_activity_types


def _write_csv(path, rows):
    if not rows:
        return
    import csv
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def test_load_all_data_empty_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        for sub in ["garmin", "stryd", "oura"]:
            os.makedirs(os.path.join(tmpdir, sub))
        data = load_all_data(tmpdir)
        assert data["garmin_activities"].empty
        assert data["oura_readiness"].empty


def test_load_all_data_with_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        for sub in ["garmin", "stryd", "oura"]:
            os.makedirs(os.path.join(tmpdir, sub))
        _write_csv(os.path.join(tmpdir, "oura", "readiness.csv"), [
            {"date": "2026-03-10", "readiness_score": "82", "hrv_avg": "45", "resting_hr": "52", "body_temperature_delta": "0.1"},
        ])
        data = load_all_data(tmpdir)
        assert len(data["oura_readiness"]) == 1
        assert data["oura_readiness"].iloc[0]["readiness_score"] == 82


class TestDiscoverActivityTypes:
    def test_returns_types_from_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "garmin"))
            _write_csv(os.path.join(tmpdir, "garmin", "activities.csv"), [
                {"activity_id": "1", "date": "2026-03-10", "activity_type": "running", "distance_km": 10},
                {"activity_id": "2", "date": "2026-03-11", "activity_type": "cycling", "distance_km": 30},
                {"activity_id": "3", "date": "2026-03-12", "activity_type": "running", "distance_km": 8},
            ])
            result = discover_activity_types(["garmin"], tmpdir)
            assert result == {"garmin": ["cycling", "running"]}

    def test_missing_csv_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = discover_activity_types(["garmin", "stryd"], tmpdir)
            assert result == {"garmin": [], "stryd": []}

    def test_csv_without_activity_type_column(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "garmin"))
            _write_csv(os.path.join(tmpdir, "garmin", "activities.csv"), [
                {"activity_id": "1", "date": "2026-03-10", "distance_km": 10},
            ])
            result = discover_activity_types(["garmin"], tmpdir)
            assert result == {"garmin": []}

    def test_unknown_provider_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = discover_activity_types(["oura"], tmpdir)
            assert result == {"oura": []}

    def test_multiple_providers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "garmin"))
            os.makedirs(os.path.join(tmpdir, "stryd"))
            _write_csv(os.path.join(tmpdir, "garmin", "activities.csv"), [
                {"activity_id": "1", "date": "2026-03-10", "activity_type": "running", "distance_km": 10},
                {"activity_id": "2", "date": "2026-03-11", "activity_type": "hiking", "distance_km": 5},
            ])
            _write_csv(os.path.join(tmpdir, "stryd", "power_data.csv"), [
                {"date": "2026-03-10", "activity_type": "running", "avg_power": 240},
            ])
            result = discover_activity_types(["garmin", "stryd"], tmpdir)
            assert result["garmin"] == ["hiking", "running"]
            assert result["stryd"] == ["running"]


    def test_empty_string_activity_types_excluded(self):
        """CSV rows with empty string activity_type should not appear in results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "garmin"))
            _write_csv(os.path.join(tmpdir, "garmin", "activities.csv"), [
                {"activity_id": "1", "date": "2026-03-10", "activity_type": "running", "distance_km": 10},
                {"activity_id": "2", "date": "2026-03-11", "activity_type": "", "distance_km": 5},
                {"activity_id": "3", "date": "2026-03-12", "activity_type": "hiking", "distance_km": 8},
            ])
            result = discover_activity_types(["garmin"], tmpdir)
            assert result == {"garmin": ["hiking", "running"]}


def test_match_activities():
    garmin = pd.DataFrame([
        {"activity_id": "1", "date": "2026-03-10", "start_time": "2026-03-10 07:00:00", "distance_km": 12.5},
        {"activity_id": "2", "date": "2026-03-11", "start_time": "2026-03-11 06:30:00", "distance_km": 8.0},
    ])
    stryd = pd.DataFrame([
        {"date": "2026-03-10", "start_time": "2026-03-10T07:01:30Z", "avg_power": 245.0, "rss": 85.0},
    ])
    merged = match_activities(garmin, stryd)
    assert len(merged) == 2
    row1 = merged[merged["activity_id"] == "1"].iloc[0]
    assert row1["avg_power"] == 245.0
    row2 = merged[merged["activity_id"] == "2"].iloc[0]
    assert pd.isna(row2["avg_power"])


def test_load_data_from_db_filters_recovery_by_preference(tmp_path):
    """When preferences.recovery is set, load_data_from_db filters
    recovery_data to only that source."""
    from datetime import date as D
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SASession

    from analysis.data_loader import load_data_from_db
    from db.models import Base, RecoveryData, User, UserConfig

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with SASession(engine) as db:
        db.add(User(id="u1", email="t@e.com", hashed_password="x"))
        db.add(UserConfig(
            user_id="u1",
            preferences={"recovery": "intervals_icu"},
        ))
        # Same date, two sources — preference should pick intervals_icu
        db.add(RecoveryData(user_id="u1", date=D(2026, 4, 20),
                            readiness_score=75, source="oura"))
        db.add(RecoveryData(user_id="u1", date=D(2026, 4, 20),
                            readiness_score=82, source="intervals_icu"))
        db.commit()

        result = load_data_from_db("u1", db)

    rec = result["recovery"]
    assert not rec.empty
    assert list(rec["source"]) == ["intervals_icu"]
    assert float(rec.iloc[0]["readiness_score"]) == 82


def test_load_data_from_db_returns_all_recovery_when_no_preference(tmp_path):
    """When preferences.recovery is unset, return all recovery rows
    (backward-compatible behavior)."""
    from datetime import date as D
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SASession

    from analysis.data_loader import load_data_from_db
    from db.models import Base, RecoveryData, User, UserConfig

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with SASession(engine) as db:
        db.add(User(id="u2", email="t2@e.com", hashed_password="x"))
        db.add(UserConfig(user_id="u2", preferences={}))
        db.add(RecoveryData(user_id="u2", date=D(2026, 4, 20),
                            readiness_score=75, source="oura"))
        db.add(RecoveryData(user_id="u2", date=D(2026, 4, 20),
                            readiness_score=82, source="intervals_icu"))
        db.commit()

        result = load_data_from_db("u2", db)

    rec = result["recovery"]
    assert len(rec) == 2


def test_load_data_from_db_returns_all_recovery_when_no_config():
    """If UserConfig row is absent entirely, don't crash — return all rows."""
    from datetime import date as D
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SASession

    from analysis.data_loader import load_data_from_db
    from db.models import Base, RecoveryData, User

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with SASession(engine) as db:
        db.add(User(id="u3", email="t3@e.com", hashed_password="x"))
        db.add(RecoveryData(user_id="u3", date=D(2026, 4, 20),
                            readiness_score=75, source="oura"))
        db.commit()

        result = load_data_from_db("u3", db)

    assert len(result["recovery"]) == 1


def test_multi_source_coexistence_garmin_and_intervals_icu():
    """End-to-end: a user with both Garmin and intervals.icu connected gets
    the right rows based on preferences.

    - Activities: both sources come through (source column preserved); filtering
      happens in api/deps.py (not exercised here — this test checks the loader
      passes all rows through with correct source attribution).
    - Recovery: preference filters to intervals_icu only.
    - Fitness: both sources come through as rows; selector disambiguates downstream.
    """
    from datetime import date as D
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SASession

    from analysis.data_loader import load_data_from_db
    from db.models import (
        Activity, Base, FitnessData, RecoveryData, User, UserConfig,
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with SASession(engine) as db:
        db.add(User(id="u1", email="t@ex.com", hashed_password="x"))
        db.add(UserConfig(
            user_id="u1",
            preferences={
                "activities": "intervals_icu",
                "recovery": "intervals_icu",
                "threshold_sources": {"cp_estimate": "intervals_icu"},
            },
        ))
        # Two activities same date, different sources — loader returns both,
        # deps.py filters to the preferred source.
        db.add(Activity(
            user_id="u1", activity_id="g_12345", date=D(2026, 4, 20),
            distance_km=10.0, duration_sec=3000, source="garmin",
        ))
        db.add(Activity(
            user_id="u1", activity_id="icu_i9000001", date=D(2026, 4, 20),
            distance_km=10.05, duration_sec=3120, source="intervals_icu",
        ))
        # Two recovery rows same date: Task 13 filter should keep only intervals_icu.
        db.add(RecoveryData(
            user_id="u1", date=D(2026, 4, 20),
            readiness_score=70, source="oura",
        ))
        db.add(RecoveryData(
            user_id="u1", date=D(2026, 4, 20),
            readiness_score=85, source="intervals_icu",
        ))
        # Fitness: cp_estimate from two sources. Loader returns both rows
        # (selector in deps.py resolves the pick).
        db.add(FitnessData(
            user_id="u1", date=D(2026, 4, 18),
            metric_type="cp_estimate", value=265.0, source="stryd",
        ))
        db.add(FitnessData(
            user_id="u1", date=D(2026, 4, 20),
            metric_type="cp_estimate", value=270.0, source="intervals_icu",
        ))
        db.commit()

        result = load_data_from_db("u1", db)

    # Activities: loader returns all rows; filtering is downstream.
    assert "source" in result["activities"].columns
    assert set(result["activities"]["source"]) == {"garmin", "intervals_icu"}
    assert len(result["activities"]) == 2

    # Recovery IS filtered at loader level per preferences.recovery (Task 13).
    assert len(result["recovery"]) == 1
    assert list(result["recovery"]["source"]) == ["intervals_icu"]
    assert float(result["recovery"].iloc[0]["readiness_score"]) == 85

    # Fitness: both rows come through to be pivoted/selected downstream.
    # fitness is pivoted wide in load_data_from_db — confirm the wide column exists.
    assert not result["fitness"].empty
    assert "cp_estimate" in result["fitness"].columns


def test_multi_source_coexistence_verifies_threshold_selector_picks_preferred():
    """Paired with the loader test above — confirm the downstream threshold
    selector picks intervals_icu when pinned, even if Stryd has a more
    recent row."""
    from datetime import date as D
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SASession

    from api.deps import _resolve_thresholds
    from db.models import Base, FitnessData, User

    # Build a minimal config-like object the selector expects.
    class _Cfg:
        preferences = {"threshold_sources": {"cp_estimate": "intervals_icu"}}
        thresholds = {}
        connections = []

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with SASession(engine) as db:
        db.add(User(id="u1", email="t@ex.com", hashed_password="x"))
        # Stryd row is MORE RECENT (date-wise) than intervals_icu. Without the
        # preference pin, the latest-by-date fallback would pick Stryd.
        db.add(FitnessData(
            user_id="u1", date=D(2026, 4, 22),
            metric_type="cp_estimate", value=265.0, source="stryd",
        ))
        db.add(FitnessData(
            user_id="u1", date=D(2026, 4, 20),
            metric_type="cp_estimate", value=270.0, source="intervals_icu",
        ))
        db.commit()

        estimate = _resolve_thresholds(_Cfg(), user_id="u1", db=db)

    # The preference pin overrides latest-by-date.
    assert estimate.cp_watts == 270.0
