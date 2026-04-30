"""Tests for fetch_activity_splits() — verifies splits and per-second samples."""
from unittest.mock import patch, MagicMock

from sync.stryd_sync import fetch_activity_splits


def _mock_response(data: dict) -> MagicMock:
    mock = MagicMock()
    mock.json.return_value = data
    mock.raise_for_status.return_value = None
    return mock


def _make_activity(
    n: int = 10,
    start_ts: int = 1000,
    lap_events: list | None = None,
    include_dynamics: bool = False,
) -> dict:
    """Build a minimal Stryd activity detail payload with n seconds of data."""
    ts = list(range(start_ts, start_ts + n))
    return {
        "timestamp_list": ts,
        "start_events": [start_ts],
        "stop_events": [start_ts + n - 1],
        "lap_events": lap_events or [],
        "total_power_list": [200.0 + i for i in range(n)],
        "heart_rate_list": [150.0 + i for i in range(n)],
        "speed_list": [3.5] * n,
        "distance_list": [i * 3.5 for i in range(n)],
        "cadence_list": [172.0] * n,
        "elevation_list": [50.0 + i * 0.1 for i in range(n)],
        "ground_time_list": [260.0] * n if include_dynamics else [],
        "oscillation_list": [71.0] * n if include_dynamics else [],
        "leg_spring_list": [11.5] * n if include_dynamics else [],
        "vertical_oscillation_ratio_list": [8.3] * n if include_dynamics else [],
        "form_power_list": [40.0] * n if include_dynamics else [],
    }


# --- Return type ---

def test_returns_tuple_of_splits_and_samples():
    """fetch_activity_splits returns (splits, samples) not a plain list."""
    payload = _make_activity(n=10, lap_events=[1005])
    with patch("sync.stryd_sync.requests.get", return_value=_mock_response(payload)):
        result = fetch_activity_splits("act-1", "token")
    assert isinstance(result, tuple)
    splits, samples = result
    assert isinstance(splits, list)
    assert isinstance(samples, list)


# --- Splits (existing behaviour must be preserved) ---

def test_splits_still_computed_correctly():
    """Lap split averages are unaffected by the new samples return value."""
    # 10 seconds, lap boundary at t=1005 → 2 laps
    payload = _make_activity(n=10, start_ts=1000, lap_events=[1005])
    with patch("sync.stryd_sync.requests.get", return_value=_mock_response(payload)):
        splits, _ = fetch_activity_splits("act-1", "token")
    assert len(splits) == 2
    assert splits[0]["activity_id"] == "act-1"
    assert splits[0]["duration_sec"] == "5"


# --- Samples field mapping ---

def test_samples_count_equals_activity_duration():
    """One sample per timestamp inside [start_ts, end_ts]."""
    n = 30
    payload = _make_activity(n=n, start_ts=2000)
    with patch("sync.stryd_sync.requests.get", return_value=_mock_response(payload)):
        _, samples = fetch_activity_splits("act-2", "token")
    assert len(samples) == n


def test_samples_core_field_mapping():
    """power_watts, hr_bpm, speed_ms, cadence_spm, altitude_m, distance_m mapped."""
    payload = _make_activity(n=5, start_ts=3000)
    with patch("sync.stryd_sync.requests.get", return_value=_mock_response(payload)):
        _, samples = fetch_activity_splits("act-3", "token")

    s = samples[0]
    assert s["activity_id"] == "act-3"
    assert s["source"] == "stryd"
    assert s["t_sec"] == 3000
    assert s["power_watts"] == 200.0
    assert s["hr_bpm"] == 150.0
    assert s["speed_ms"] == 3.5
    assert s["cadence_spm"] == 172.0
    assert s["altitude_m"] == 50.0
    assert s["distance_m"] == 0.0


def test_samples_stryd_dynamics_mapped():
    """Stryd running dynamics columns are populated when present."""
    payload = _make_activity(n=5, start_ts=4000, include_dynamics=True)
    with patch("sync.stryd_sync.requests.get", return_value=_mock_response(payload)):
        _, samples = fetch_activity_splits("act-4", "token")

    s = samples[0]
    assert s["ground_time_ms"] == 260.0
    assert s["oscillation_mm"] == 71.0
    assert s["leg_spring_kn_m"] == 11.5
    assert s["vertical_ratio"] == 8.3
    assert s["form_power_watts"] == 40.0


def test_samples_dynamics_none_when_missing():
    """Stryd dynamics columns are None when lists are absent from the payload."""
    payload = _make_activity(n=5, start_ts=5000, include_dynamics=False)
    with patch("sync.stryd_sync.requests.get", return_value=_mock_response(payload)):
        _, samples = fetch_activity_splits("act-5", "token")

    s = samples[0]
    assert s["ground_time_ms"] is None
    assert s["oscillation_mm"] is None
    assert s["leg_spring_kn_m"] is None


def test_samples_bounded_to_activity_window():
    """Timestamps outside [start_ts, end_ts] are excluded from samples."""
    n = 10
    payload = _make_activity(n=n, start_ts=6000)
    # Add padding timestamps outside the activity window
    payload["timestamp_list"] = [5998, 5999] + payload["timestamp_list"] + [6010, 6011]
    payload["total_power_list"] = [0.0, 0.0] + payload["total_power_list"] + [0.0, 0.0]
    payload["heart_rate_list"] = [0.0, 0.0] + payload["heart_rate_list"] + [0.0, 0.0]
    payload["speed_list"] = [0.0, 0.0] + payload["speed_list"] + [0.0, 0.0]
    payload["distance_list"] = [0.0, 0.0] + payload["distance_list"] + [0.0, 0.0]

    with patch("sync.stryd_sync.requests.get", return_value=_mock_response(payload)):
        _, samples = fetch_activity_splits("act-6", "token")

    t_secs = [s["t_sec"] for s in samples]
    assert 5998 not in t_secs
    assert 5999 not in t_secs
    assert 6010 not in t_secs
    assert len(samples) == n


# --- Empty / degenerate payloads ---

def test_empty_payload_returns_empty_lists():
    """Missing timestamp_list or power_list returns ([], [])."""
    with patch("sync.stryd_sync.requests.get", return_value=_mock_response({})):
        splits, samples = fetch_activity_splits("act-7", "token")
    assert splits == []
    assert samples == []


def test_no_lap_events_produces_one_split():
    """Activity with no lap boundaries produces a single split and full samples."""
    payload = _make_activity(n=20, start_ts=7000, lap_events=[])
    with patch("sync.stryd_sync.requests.get", return_value=_mock_response(payload)):
        splits, samples = fetch_activity_splits("act-8", "token")
    assert len(splits) == 1
    assert len(samples) == 20
