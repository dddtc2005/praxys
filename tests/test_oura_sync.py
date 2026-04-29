import json
from unittest.mock import patch, MagicMock
from sync.oura_sync import (
    fetch_sleep_data, fetch_readiness_data,
    parse_sleep_records, parse_readiness_records,
    select_oura_hrv_per_day,
)

SAMPLE_SLEEP_RESPONSE = {
    "data": [
        {
            "day": "2026-03-10",
            "total_sleep_duration": 28800,
            "deep_sleep_duration": 7200,
            "rem_sleep_duration": 5400,
            "light_sleep_duration": 16200,
            "efficiency": 92,
            "readiness": {"score": 85},
            "average_hrv": 45,
            "average_heart_rate": 52,
        }
    ],
    "next_token": None,
}

SAMPLE_READINESS_RESPONSE = {
    "data": [
        {
            "day": "2026-03-10",
            "score": 82,
            "temperature_deviation": 0.1,
            "timestamp": "2026-03-10T08:00:00+00:00",
        }
    ],
    "next_token": None,
}


def test_parse_sleep_records():
    records = parse_sleep_records(SAMPLE_SLEEP_RESPONSE["data"])
    assert len(records) == 1
    r = records[0]
    assert r["date"] == "2026-03-10"
    assert r["total_sleep_sec"] == "28800"
    assert r["deep_sleep_sec"] == "7200"
    assert r["efficiency"] == "92"
    assert r["sleep_score"] == "85"


def test_parse_readiness_records():
    records = parse_readiness_records(SAMPLE_READINESS_RESPONSE["data"])
    assert len(records) == 1
    r = records[0]
    assert r["date"] == "2026-03-10"
    assert r["readiness_score"] == "82"
    assert r["body_temperature_delta"] == "0.1"


@patch("sync.oura_sync.requests.get")
def test_fetch_sleep_data(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_SLEEP_RESPONSE
    mock_get.return_value = mock_resp

    data = fetch_sleep_data("fake_token", "2026-03-01", "2026-03-10")
    assert len(data) == 1
    mock_get.assert_called_once()
    call_url = mock_get.call_args[0][0]
    assert "/sleep" in call_url


@patch("sync.oura_sync.requests.get")
def test_fetch_readiness_data(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = SAMPLE_READINESS_RESPONSE
    mock_get.return_value = mock_resp

    data = fetch_readiness_data("fake_token", "2026-03-01", "2026-03-10")
    assert len(data) == 1


# ---------------------------------------------------------------------------
# select_oura_hrv_per_day — multi-record-per-day tiebreak
#
# Production data-loss path: Oura returns long_sleep + late_nap + rest for the
# same `day`, naps come back with `average_hrv: null`, and a naive
# last-write-wins dict lets the nap clobber the long_sleep's valid HRV. Once
# the writer's existing-date dedup locks that null in, recovery analysis
# stalls on "Insufficient HRV data" forever.
# ---------------------------------------------------------------------------


def _record(day: str, hrv, hr, type_: str | None = "long_sleep") -> dict:
    rec: dict = {"day": day, "average_hrv": hrv, "average_heart_rate": hr}
    if type_ is not None:
        rec["type"] = type_
    return rec


def test_select_oura_hrv_long_sleep_beats_nap_with_null_hrv():
    """The exact production failure mode: nap with null HRV must not win."""
    sleep_raw = [
        _record("2026-04-29", 45, 52, type_="long_sleep"),
        _record("2026-04-29", None, None, type_="late_nap"),
    ]
    out = select_oura_hrv_per_day(sleep_raw)
    assert out["2026-04-29"]["hrv_avg"] == "45"
    assert out["2026-04-29"]["resting_hr"] == "52"
    assert out["2026-04-29"]["_type"] == "long_sleep"


def test_select_oura_hrv_order_independent_for_null_naps():
    """Order shouldn't matter — long_sleep with HRV always beats null naps."""
    sleep_raw = [
        _record("2026-04-29", None, None, type_="late_nap"),
        _record("2026-04-29", 45, 52, type_="long_sleep"),
    ]
    out = select_oura_hrv_per_day(sleep_raw)
    assert out["2026-04-29"]["hrv_avg"] == "45"


def test_select_oura_hrv_long_sleep_beats_rest_with_hrv():
    """When both records have positive HRV, long_sleep wins (even when rest sorts last)."""
    sleep_raw = [
        _record("2026-04-29", 45, 52, type_="long_sleep"),
        _record("2026-04-29", 38, 60, type_="rest"),
    ]
    out = select_oura_hrv_per_day(sleep_raw)
    assert out["2026-04-29"]["hrv_avg"] == "45"
    assert out["2026-04-29"]["_type"] == "long_sleep"


def test_select_oura_hrv_falls_back_to_nap_when_long_sleep_missing_hrv():
    """If only the nap has HRV, it wins — the alternative is null HRV."""
    sleep_raw = [
        _record("2026-04-29", None, None, type_="long_sleep"),
        _record("2026-04-29", 38, 60, type_="late_nap"),
    ]
    out = select_oura_hrv_per_day(sleep_raw)
    assert out["2026-04-29"]["hrv_avg"] == "38"


def test_select_oura_hrv_handles_missing_or_null_type():
    """`type` may be missing or JSON null — long_sleep candidate still wins."""
    sleep_raw = [
        _record("2026-04-29", 45, 52, type_=None),  # missing
        _record("2026-04-29", 50, 55, type_="long_sleep"),
    ]
    out = select_oura_hrv_per_day(sleep_raw)
    assert out["2026-04-29"]["hrv_avg"] == "50"
    assert out["2026-04-29"]["_type"] == "long_sleep"


def test_select_oura_hrv_skips_records_without_day():
    """Records with empty/missing `day` are dropped silently."""
    sleep_raw = [
        {"day": "", "average_hrv": 45, "average_heart_rate": 52, "type": "long_sleep"},
        {"average_hrv": 50, "average_heart_rate": 55, "type": "long_sleep"},
        _record("2026-04-29", 45, 52, type_="long_sleep"),
    ]
    out = select_oura_hrv_per_day(sleep_raw)
    assert list(out.keys()) == ["2026-04-29"]


def test_select_oura_hrv_zero_treated_as_invalid():
    """An average_hrv of 0 (occasional sensor glitch) shouldn't block a real reading."""
    sleep_raw = [
        _record("2026-04-29", 0, 0, type_="long_sleep"),
        _record("2026-04-29", 42, 50, type_="late_nap"),
    ]
    out = select_oura_hrv_per_day(sleep_raw)
    assert out["2026-04-29"]["hrv_avg"] == "42"
