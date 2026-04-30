"""Tests for parse_activity_stream() in sync/coros_sync.py.

NOTE: COROS field names are UNVERIFIED against real hardware. These tests
validate the parsing logic against the expected response shape documented
in the COROS Sport Open API. A COROS user must run a real sync and confirm
row counts and field values before this implementation is considered stable.
"""
import pytest
from sync.coros_sync import parse_activity_stream


def _make_detail(
    n: int = 5,
    start_ts: int = 1_777_000_000,
    key: str = "trackPoints",
    include_gps: bool = True,
    include_power: bool = False,
) -> dict:
    """Build a minimal COROS activity detail payload with n track points."""
    points = []
    for i in range(n):
        pt = {
            "timestamp": start_ts + i,
            "heartRate": 150 + i,
            "cadence": 172,
            "speed": 3.5,
            "altitude": 50.0 + i * 0.1,
        }
        if include_gps:
            pt["latitude"] = 31.18 + i * 0.001
            pt["longitude"] = 121.25 + i * 0.001
        if include_power:
            pt["power"] = 220 + i
        points.append(pt)
    return {key: points}


def test_returns_one_sample_per_track_point():
    """Each trackPoints entry produces one sample."""
    detail = _make_detail(n=10)
    samples = parse_activity_stream("act-1", detail)
    assert len(samples) == 10


def test_returns_empty_when_no_track_points():
    """Returns [] when neither trackPoints nor trackingPoints present."""
    assert parse_activity_stream("act-2", {}) == []
    assert parse_activity_stream("act-3", {"lapList": []}) == []


def test_fallback_key_trackingpoints():
    """Also accepts trackingPoints as the list key."""
    detail = _make_detail(n=5, key="trackingPoints")
    samples = parse_activity_stream("act-4", detail)
    assert len(samples) == 5


def test_core_fields_mapped():
    """hr_bpm, cadence_spm, speed_ms, altitude_m populated."""
    detail = _make_detail(n=1, start_ts=2_000_000_000)
    s = parse_activity_stream("act-5", detail)[0]
    assert s["source"] == "coros"
    assert s["activity_id"] == "act-5"
    assert s["t_sec"] == 2_000_000_000
    assert s["hr_bpm"] == 150
    assert s["cadence_spm"] == 172
    assert s["speed_ms"] == pytest.approx(3.5)
    assert s["altitude_m"] == pytest.approx(50.0)


def test_gps_populated():
    """lat and lng extracted from latitude/longitude fields."""
    detail = _make_detail(n=1, include_gps=True)
    s = parse_activity_stream("act-6", detail)[0]
    assert s["lat"] == pytest.approx(31.18)
    assert s["lng"] == pytest.approx(121.25)


def test_gps_none_when_absent():
    """lat/lng are None when GPS fields missing."""
    detail = _make_detail(n=1, include_gps=False)
    s = parse_activity_stream("act-7", detail)[0]
    assert s["lat"] is None
    assert s["lng"] is None


def test_power_populated_when_present():
    """power_watts extracted when field present."""
    detail = _make_detail(n=1, include_power=True)
    s = parse_activity_stream("act-8", detail)[0]
    assert s["power_watts"] == 220


def test_power_none_when_absent():
    """power_watts is None when not in track point."""
    detail = _make_detail(n=1, include_power=False)
    s = parse_activity_stream("act-9", detail)[0]
    assert s["power_watts"] is None


def test_missing_timestamp_row_skipped():
    """Points without a timestamp are skipped."""
    detail = _make_detail(n=3)
    detail["trackPoints"][1].pop("timestamp")
    samples = parse_activity_stream("act-10", detail)
    assert len(samples) == 2


def test_1hz_sampling_preserved():
    """1-second intervals preserved in t_sec values."""
    detail = _make_detail(n=5, start_ts=3_000_000_000)
    samples = parse_activity_stream("act-11", detail)
    for i in range(1, len(samples)):
        assert samples[i]["t_sec"] - samples[i - 1]["t_sec"] == 1
