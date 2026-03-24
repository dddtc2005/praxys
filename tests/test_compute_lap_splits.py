"""Tests for compute_lap_splits and _migrate_config."""
from sync.stryd_sync import compute_lap_splits
from analysis.config import _migrate_config


# --- compute_lap_splits ---


def _make_activity(
    timestamps: list[int],
    lap_timestamps: list[int],
    power: list | None = None,
    hr: list | None = None,
    cadence: list | None = None,
    speed: list | None = None,
    distance: list | None = None,
    elevation: list | None = None,
) -> dict:
    """Build a minimal Stryd activity detail dict for testing."""
    n = len(timestamps)
    return {
        "timestamp_list": timestamps,
        "lap_timestamp_list": lap_timestamps,
        "total_power_list": power or [200] * n,
        "heart_rate_list": hr or [150] * n,
        "cadence_list": cadence or [170] * n,
        "speed_list": speed or [3.0] * n,
        "distance_list": distance or [i * 3 for i in range(n)],
        "elevation_list": elevation or [5.0] * n,
        "ground_time_list": [260] * n,
        "oscillation_list": [6.5] * n,
        "leg_spring_list": [9.5] * n,
    }


def test_happy_path_three_laps():
    """Three laps with clean data should produce 3 splits."""
    ts = list(range(100, 400))  # 300 seconds
    lap_ts = [200, 300]  # 3 laps: 100-200, 200-300, 300-399
    power = [180] * 100 + [250] * 100 + [190] * 100

    activity = _make_activity(ts, lap_ts, power=power)
    splits = compute_lap_splits(activity, "12345")

    assert len(splits) == 3
    assert splits[0]["activity_id"] == "12345"
    assert splits[0]["split_num"] == "1"
    assert splits[1]["split_num"] == "2"
    assert splits[2]["split_num"] == "3"

    # Power averages should reflect the per-lap data
    assert float(splits[0]["avg_power"]) == 180.0
    assert float(splits[1]["avg_power"]) == 250.0
    assert float(splits[2]["avg_power"]) == 190.0


def test_includes_last_lap():
    """Data after the last lap marker must be included (not dropped)."""
    ts = list(range(0, 100))
    lap_ts = [50]  # One lap marker at 50 → should produce 2 laps: 0-50, 50-99
    power = [200] * 50 + [300] * 50

    activity = _make_activity(ts, lap_ts, power=power)
    splits = compute_lap_splits(activity, "99")

    assert len(splits) == 2
    assert float(splits[1]["avg_power"]) == 300.0


def test_empty_lap_timestamps_returns_empty():
    """No lap timestamps → no splits."""
    activity = _make_activity(list(range(10)), [])
    assert compute_lap_splits(activity, "1") == []


def test_empty_timestamp_list_returns_empty():
    """No timestamp data → no splits."""
    activity = _make_activity([], [5])
    assert compute_lap_splits(activity, "1") == []


def test_boundary_noise_filter():
    """Lap boundaries < 10 seconds apart should be merged."""
    ts = list(range(0, 100))
    # Two boundaries 5s apart — should merge to one
    lap_ts = [50, 55]
    power = [200] * 50 + [300] * 50

    activity = _make_activity(ts, lap_ts, power=power)
    splits = compute_lap_splits(activity, "1")

    # Should produce 2 laps (0-50, 50-99), not 3
    assert len(splits) == 2


def test_distance_and_elevation():
    """Distance and elevation change computed correctly per lap."""
    ts = list(range(0, 60))  # 60 seconds
    lap_ts = [30]  # 2 laps: 0-30, 30-59
    distance = [i * 5 for i in range(60)]  # 5 meters per second cumulative
    # Gradual elevation rise in lap 1, flat in lap 2
    elevation = [float(i) for i in range(30)] + [29.0] * 30

    activity = _make_activity(ts, lap_ts, distance=distance, elevation=elevation)
    splits = compute_lap_splits(activity, "1")

    assert len(splits) == 2
    assert float(splits[0]["distance_km"]) > 0
    # First lap: elevation rises from 0 to 29 = +29.0m
    assert float(splits[0]["elevation_change_m"]) == 29.0
    # Second lap: flat at 29.0
    assert float(splits[1]["elevation_change_m"]) == 0.0


def test_pace_derived_from_speed():
    """Pace should be 1000/speed in sec/km."""
    ts = list(range(0, 20))
    lap_ts = [10]
    speed = [4.0] * 20  # 4 m/s = 250 sec/km

    activity = _make_activity(ts, lap_ts, speed=speed)
    splits = compute_lap_splits(activity, "1")

    assert float(splits[0]["avg_pace_sec_km"]) == 250.0


def test_none_values_in_data():
    """None values in time-series should be skipped in averages."""
    ts = list(range(0, 60))  # 60 seconds
    lap_ts = [30]  # 2 laps: 0-30, 30-59
    power = ([200, None] * 15) + ([300, None] * 15)

    activity = _make_activity(ts, lap_ts, power=power)
    splits = compute_lap_splits(activity, "1")

    assert len(splits) == 2
    assert float(splits[0]["avg_power"]) == 200.0
    assert float(splits[1]["avg_power"]) == 300.0


def test_zero_power_included():
    """Zero power values should be included in averages (not filtered out)."""
    ts = list(range(0, 60))
    lap_ts = [30]
    # Mix of 0 and 200 — average should be 100, not 200
    power = [0, 200] * 15 + [100] * 30

    activity = _make_activity(ts, lap_ts, power=power)
    splits = compute_lap_splits(activity, "1")

    assert len(splits) == 2
    assert float(splits[0]["avg_power"]) == 100.0  # (0+200)*15/30 = 100


# --- _migrate_config ---


def test_migrate_old_format():
    """Old sources format should migrate to connections + preferences."""
    old = {
        "training_base": "power",
        "sources": {"activities": "garmin", "health": "oura", "plan": "stryd"},
    }
    result = _migrate_config(old)

    assert "sources" not in result
    assert result["connections"] == ["garmin", "oura", "stryd"]
    assert result["preferences"]["activities"] == "garmin"
    assert result["preferences"]["recovery"] == "oura"  # health → recovery
    assert result["preferences"]["plan"] == "stryd"


def test_migrate_deduplicates_connections():
    """If same platform appears multiple times in sources, connections should deduplicate."""
    old = {
        "sources": {"activities": "garmin", "health": "garmin", "plan": "stryd"},
    }
    result = _migrate_config(old)

    assert result["connections"] == ["garmin", "stryd"]


def test_migrate_new_format_unchanged():
    """Already-new-format config should pass through unchanged."""
    new = {
        "connections": ["garmin", "oura"],
        "preferences": {"activities": "garmin", "recovery": "oura", "plan": ""},
    }
    result = _migrate_config(new.copy())

    assert result["connections"] == ["garmin", "oura"]
    assert result["preferences"]["recovery"] == "oura"


def test_migrate_bare_defaults():
    """Config with neither sources nor connections should pass through."""
    bare = {"training_base": "power"}
    result = _migrate_config(bare)

    assert "connections" not in result  # Not added — UserConfig defaults handle this
    assert result["training_base"] == "power"
