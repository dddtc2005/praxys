"""Tests for fetch_activity_streams() and parse_activity_stream() in sync/strava_sync.py."""
import pytest
from unittest.mock import patch, MagicMock

from sync.strava_sync import fetch_activity_streams, parse_activity_stream


def _mock_response(data: dict) -> MagicMock:
    m = MagicMock()
    m.json.return_value = data
    m.raise_for_status.return_value = None
    return m


def _make_streams(
    n: int = 5,
    start_offset: int = 0,
    include_power: bool = True,
    include_gps: bool = True,
    include_grade: bool = True,
    include_temp: bool = True,
) -> dict:
    """Build a minimal Strava streams response with n data points."""
    streams: dict = {
        "time": {"data": list(range(start_offset, start_offset + n))},
        "heartrate": {"data": [150 + i for i in range(n)]},
        "velocity_smooth": {"data": [3.5] * n},
        "cadence": {"data": [86] * n},          # strides/min → ×2 = 172 spm
        "altitude": {"data": [50.0 + i * 0.1 for i in range(n)]},
        "distance": {"data": [i * 3.5 for i in range(n)]},
    }
    if include_power:
        streams["watts"] = {"data": [220 + i for i in range(n)]}
    if include_gps:
        streams["latlng"] = {"data": [[31.18 + i * 0.001, 121.25 + i * 0.001] for i in range(n)]}
    if include_grade:
        streams["grade_smooth"] = {"data": [1.0 + i * 0.1 for i in range(n)]}
    if include_temp:
        streams["temp"] = {"data": [22.0] * n}
    return streams


START_DATE = "2026-04-26T05:30:00Z"
START_TS = 1777181400  # unix timestamp for 2026-04-26T05:30:00Z


# --- fetch_activity_streams ---

def test_fetch_passes_correct_params():
    """fetch_activity_streams sends key_by_type=true and all stream keys."""
    with patch("sync.strava_sync.requests.get", return_value=_mock_response({})) as mock_get:
        fetch_activity_streams("123", "tok")
    call_params = mock_get.call_args[1]["params"]
    assert call_params["key_by_type"] == "true"
    assert "heartrate" in call_params["keys"]
    assert "latlng" in call_params["keys"]


# --- parse_activity_stream ---

def test_returns_one_sample_per_time_offset():
    """Each time offset produces one sample."""
    streams = _make_streams(n=10)
    samples = parse_activity_stream("act-1", streams, START_DATE)
    assert len(samples) == 10


def test_timestamp_computed_from_start_date_plus_offset():
    """t_sec = unix(start_date) + time_offset."""
    streams = _make_streams(n=1, start_offset=0)
    s = parse_activity_stream("act-2", streams, START_DATE)[0]
    assert s["t_sec"] == START_TS


def test_time_offset_added_correctly():
    """Offset of 60 adds 60 seconds to the start timestamp."""
    streams = _make_streams(n=1, start_offset=60)
    s = parse_activity_stream("act-3", streams, START_DATE)[0]
    assert s["t_sec"] == START_TS + 60


def test_cadence_doubled():
    """Strava cadence is strides/min; multiplied by 2 for steps/min."""
    streams = _make_streams(n=1)  # cadence=86 strides/min
    s = parse_activity_stream("act-4", streams, START_DATE)[0]
    assert s["cadence_spm"] == 172


def test_core_fields_mapped():
    """power, hr, speed, altitude, distance populated."""
    streams = _make_streams(n=1)
    s = parse_activity_stream("act-5", streams, START_DATE)[0]
    assert s["source"] == "strava"
    assert s["activity_id"] == "act-5"
    assert s["power_watts"] == 220
    assert s["hr_bpm"] == 150
    assert s["speed_ms"] == pytest.approx(3.5)
    assert s["altitude_m"] == pytest.approx(50.0)
    assert s["distance_m"] == pytest.approx(0.0)


def test_gps_unpacked_from_latlng():
    """lat/lng extracted from nested [lat, lng] list."""
    streams = _make_streams(n=1, include_gps=True)
    s = parse_activity_stream("act-6", streams, START_DATE)[0]
    assert s["lat"] == pytest.approx(31.18)
    assert s["lng"] == pytest.approx(121.25)


def test_gps_none_when_absent():
    """lat/lng are None when latlng stream not in response."""
    streams = _make_streams(n=1, include_gps=False)
    s = parse_activity_stream("act-7", streams, START_DATE)[0]
    assert s["lat"] is None
    assert s["lng"] is None


def test_grade_and_temperature_populated():
    """grade_pct and temperature_c extracted."""
    streams = _make_streams(n=1, include_grade=True, include_temp=True)
    s = parse_activity_stream("act-8", streams, START_DATE)[0]
    assert s["grade_pct"] == pytest.approx(1.0)
    assert s["temperature_c"] == pytest.approx(22.0)


def test_power_none_when_no_watts_stream():
    """power_watts is None when watts stream absent (no power meter)."""
    streams = _make_streams(n=1, include_power=False)
    s = parse_activity_stream("act-9", streams, START_DATE)[0]
    assert s["power_watts"] is None


def test_empty_time_stream_returns_empty():
    """Missing or empty time stream returns []."""
    assert parse_activity_stream("act-10", {}, START_DATE) == []
    assert parse_activity_stream("act-11", {"time": {"data": []}}, START_DATE) == []


def test_invalid_start_date_returns_empty():
    """Unparseable start_date returns []."""
    streams = _make_streams(n=3)
    assert parse_activity_stream("act-12", streams, "not-a-date") == []
    assert parse_activity_stream("act-13", streams, "") == []


def test_consecutive_t_sec_values():
    """t_sec increments by 1 second for 1-second sampled data."""
    streams = _make_streams(n=5, start_offset=0)
    samples = parse_activity_stream("act-14", streams, START_DATE)
    for i in range(1, len(samples)):
        assert samples[i]["t_sec"] - samples[i - 1]["t_sec"] == 1
