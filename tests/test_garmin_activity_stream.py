"""Tests for parse_activity_stream() in sync/garmin_sync.py."""
import pytest
from sync.garmin_sync import parse_activity_stream


def _make_details(
    n: int = 5,
    start_ms: int = 1_000_000_000_000,
    step_ms: int = 2000,
    include_gps: bool = True,
    include_dynamics: bool = True,
) -> dict:
    """Build a minimal get_activity_details() response with n rows."""
    descriptors = [
        {"metricsIndex": 0, "key": "directTimestamp"},
        {"metricsIndex": 1, "key": "directHeartRate"},
        {"metricsIndex": 2, "key": "directDoubleCadence"},
        {"metricsIndex": 3, "key": "directSpeed"},
        {"metricsIndex": 4, "key": "directElevation"},
        {"metricsIndex": 5, "key": "sumDistance"},
        {"metricsIndex": 6, "key": "directLatitude"},
        {"metricsIndex": 7, "key": "directLongitude"},
        {"metricsIndex": 8, "key": "directGroundContactTime"},
        {"metricsIndex": 9, "key": "directVerticalOscillation"},
        {"metricsIndex": 10, "key": "directVerticalRatio"},
    ]
    rows = []
    for i in range(n):
        ts = start_ms + i * step_ms
        metrics = [
            float(ts),          # 0 directTimestamp (ms)
            150.0 + i,          # 1 directHeartRate
            172.0,              # 2 directDoubleCadence
            3.5,                # 3 directSpeed (m/s)
            50.0 + i * 0.1,    # 4 directElevation
            i * 7.0,            # 5 sumDistance (cumulative m)
            31.18 + i * 0.001 if include_gps else None,  # 6 lat
            121.25 + i * 0.001 if include_gps else None, # 7 lng
            260.0 if include_dynamics else None,          # 8 ground_time
            7.2 if include_dynamics else None,            # 9 oscillation
            6.8 if include_dynamics else None,            # 10 vertical_ratio
        ]
        rows.append({"metrics": metrics})
    return {"metricDescriptors": descriptors, "activityDetailMetrics": rows}


def test_returns_one_sample_per_row():
    """Each activityDetailMetrics row produces one sample."""
    details = _make_details(n=10)
    samples = parse_activity_stream("act-1", details)
    assert len(samples) == 10


def test_timestamp_converted_from_ms_to_sec():
    """directTimestamp (milliseconds) is divided by 1000 for t_sec."""
    details = _make_details(n=1, start_ms=1_777_540_905_000)
    samples = parse_activity_stream("act-2", details)
    assert samples[0]["t_sec"] == 1_777_540_905


def test_two_second_sampling_preserved():
    """2-second step between rows is reflected in consecutive t_sec values."""
    details = _make_details(n=3, start_ms=1_000_000_000_000, step_ms=2000)
    samples = parse_activity_stream("act-3", details)
    assert samples[1]["t_sec"] - samples[0]["t_sec"] == 2
    assert samples[2]["t_sec"] - samples[1]["t_sec"] == 2


def test_core_fields_mapped():
    """hr_bpm, cadence_spm, speed_ms, altitude_m, distance_m populated."""
    details = _make_details(n=1)
    s = parse_activity_stream("act-4", details)[0]
    assert s["source"] == "garmin"
    assert s["activity_id"] == "act-4"
    assert s["hr_bpm"] == 150.0
    assert s["cadence_spm"] == 172.0
    assert s["speed_ms"] == 3.5
    assert s["altitude_m"] == pytest.approx(50.0)
    assert s["distance_m"] == 0.0


def test_gps_fields_populated():
    """lat and lng extracted when directLatitude/directLongitude present."""
    details = _make_details(n=1, include_gps=True)
    s = parse_activity_stream("act-5", details)[0]
    assert s["lat"] == pytest.approx(31.18)
    assert s["lng"] == pytest.approx(121.25)


def test_gps_none_when_missing():
    """lat and lng are None when GPS metrics absent from row."""
    details = _make_details(n=1, include_gps=False)
    s = parse_activity_stream("act-6", details)[0]
    assert s["lat"] is None
    assert s["lng"] is None


def test_dynamics_populated():
    """ground_time_ms, oscillation_mm, vertical_ratio extracted."""
    details = _make_details(n=1, include_dynamics=True)
    s = parse_activity_stream("act-7", details)[0]
    assert s["ground_time_ms"] == 260.0
    assert s["oscillation_mm"] == 7.2
    assert s["vertical_ratio"] == pytest.approx(6.8)


def test_no_power_in_output():
    """power_watts is not in the sample dict — unavailable in Garmin stream."""
    details = _make_details(n=1)
    s = parse_activity_stream("act-8", details)[0]
    assert "power_watts" not in s


def test_dynamic_descriptor_order():
    """Index mapping is built from metricDescriptors regardless of order."""
    details = _make_details(n=1)
    # Shuffle the descriptor order
    details["metricDescriptors"] = list(reversed(details["metricDescriptors"]))
    # Metrics array order is still by metricsIndex, not descriptor list order
    samples = parse_activity_stream("act-9", details)
    assert len(samples) == 1
    assert samples[0]["hr_bpm"] == 150.0


def test_missing_timestamp_row_skipped():
    """Rows with None timestamp are skipped."""
    details = _make_details(n=3)
    details["activityDetailMetrics"][1]["metrics"][0] = None
    samples = parse_activity_stream("act-10", details)
    assert len(samples) == 2


def test_empty_payload_returns_empty():
    """Missing descriptors or rows returns empty list."""
    assert parse_activity_stream("act-11", {}) == []
    assert parse_activity_stream("act-12", {"metricDescriptors": [], "activityDetailMetrics": []}) == []


def test_missing_directtimestamp_descriptor_returns_empty():
    """Without directTimestamp in descriptors, cannot build samples."""
    details = _make_details(n=3)
    details["metricDescriptors"] = [
        m for m in details["metricDescriptors"] if m["key"] != "directTimestamp"
    ]
    assert parse_activity_stream("act-13", details) == []
