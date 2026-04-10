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
