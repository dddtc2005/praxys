from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from sync.intervals_icu_sync import INTERVALS_BASE_URL, _build_auth, _request


def test_build_auth_uses_api_key_username_form():
    """HTTP Basic auth: username is literal 'API_KEY', password is user PAT.

    Verified V1 against live API on 2026-04-22. The alternate form
    (username=athlete_id) returned 403.
    """
    auth = _build_auth({"athlete_id": "i123456", "api_key": "secret-pat"})
    assert auth == ("API_KEY", "secret-pat")


def _mock_response(status_code: int = 200, json_payload=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_payload or {}
    if status_code >= 400:
        def _raise():
            from requests import HTTPError
            raise HTTPError(response=resp)
        resp.raise_for_status.side_effect = _raise
    else:
        resp.raise_for_status.return_value = None
    return resp


@patch("sync.intervals_icu_sync.requests.get")
def test_request_returns_json_on_200(mock_get):
    mock_get.return_value = _mock_response(200, {"ok": True})
    result = _request("/athlete/i1", credentials={"athlete_id": "i1", "api_key": "k"})
    assert result == {"ok": True}
    mock_get.assert_called_once()
    call_kwargs = mock_get.call_args.kwargs
    assert call_kwargs["auth"] == ("API_KEY", "k")
    assert call_kwargs["timeout"] == 15
    assert "praxys" in call_kwargs["headers"]["User-Agent"]


@patch("sync.intervals_icu_sync.requests.get")
def test_request_401_raises_unauthorized(mock_get):
    from sync.intervals_icu_sync import IntervalsIcuUnauthorized
    mock_get.return_value = _mock_response(401)
    with pytest.raises(IntervalsIcuUnauthorized):
        _request("/athlete/i1", credentials={"athlete_id": "i1", "api_key": "k"})


@patch("sync.intervals_icu_sync.time.sleep")
@patch("sync.intervals_icu_sync.requests.get")
def test_request_429_retries_with_backoff(mock_get, mock_sleep):
    mock_get.side_effect = [
        _mock_response(429),
        _mock_response(429),
        _mock_response(200, {"ok": True}),
    ]
    result = _request("/athlete/i1", credentials={"athlete_id": "i1", "api_key": "k"})
    assert result == {"ok": True}
    assert mock_get.call_count == 3
    assert mock_sleep.call_args_list[0].args[0] == 1.0
    assert mock_sleep.call_args_list[1].args[0] == 2.0


@patch("sync.intervals_icu_sync.time.sleep")
@patch("sync.intervals_icu_sync.requests.get")
def test_request_429_exhausts_retries(mock_get, mock_sleep):
    from sync.intervals_icu_sync import IntervalsIcuRateLimited
    mock_get.return_value = _mock_response(429)
    with pytest.raises(IntervalsIcuRateLimited):
        _request("/athlete/i1", credentials={"athlete_id": "i1", "api_key": "k"})
    assert mock_get.call_count == 4  # MAX_RETRIES


import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent.parent / "data" / "sample" / "intervals_icu"


def _load_fixture(name: str):
    return json.loads((FIXTURE_DIR / name).read_text())


def test_parse_activity_applies_icu_prefix_to_id():
    from sync.intervals_icu_sync import _parse_activity
    activity = _load_fixture("activities.json")[0]
    row = _parse_activity(activity)
    assert row["activity_id"] == "icu_i9000001"
    assert row["source"] == "intervals_icu"


def test_parse_activity_uses_local_date_prefix_only():
    from sync.intervals_icu_sync import _parse_activity
    activity = _load_fixture("activities.json")[0]
    row = _parse_activity(activity)
    assert row["date"] == "2026-04-18"


def test_parse_activity_maps_run_to_running():
    from sync.intervals_icu_sync import _parse_activity
    activity = _load_fixture("activities.json")[0]
    row = _parse_activity(activity)
    assert row["activity_type"] == "running"


def test_parse_activity_converts_meters_and_computes_pace():
    from sync.intervals_icu_sync import _parse_activity
    activity = _load_fixture("activities.json")[0]
    row = _parse_activity(activity)
    # 10050m = 10.05km
    assert float(row["distance_km"]) == pytest.approx(10.05, abs=0.001)
    # 3120s / 10.05km ~ 310.4 sec/km
    assert float(row["avg_pace_sec_km"]) == pytest.approx(310.4, abs=0.5)


def test_parse_activity_prefers_icu_average_watts_over_average_watts():
    from sync.intervals_icu_sync import _parse_activity
    activity = _load_fixture("activities.json")[0].copy()
    activity["icu_average_watts"] = 280
    activity["average_watts"] = 220
    row = _parse_activity(activity)
    assert float(row["avg_power"]) == 280


def test_parse_activity_doubles_cadence_for_run():
    """intervals.icu reports single-leg cadence; Praxys stores double-leg spm."""
    from sync.intervals_icu_sync import _parse_activity
    activity = _load_fixture("activities.json")[0]
    # fixture has average_cadence=87.5 single-leg -> 175 spm
    row = _parse_activity(activity)
    assert float(row["avg_cadence"]) == pytest.approx(175.0, abs=0.1)


def test_parse_activity_leaves_derived_load_metrics_null():
    """Per scientific-rigor principle, Praxys computes RSS/TRIMP itself."""
    from sync.intervals_icu_sync import _parse_activity
    activity = _load_fixture("activities.json")[0]
    row = _parse_activity(activity)
    assert row.get("rss") in (None, "")
    assert row.get("trimp") in (None, "")
    assert row.get("training_effect") in (None, "")


def test_parse_activity_with_null_power_yields_empty_strings():
    from sync.intervals_icu_sync import _parse_activity
    activity = _load_fixture("activities.json")[1]  # the null-power run
    row = _parse_activity(activity)
    assert row["avg_power"] in (None, "")
    assert row["max_power"] in (None, "")


def test_parse_activity_maps_virtual_run_to_running():
    """V4 verified: VirtualRun activity type maps to running."""
    from sync.intervals_icu_sync import _parse_activity
    activity = {
        "id": "i9900001",
        "start_date_local": "2026-04-19T08:00:00",
        "type": "VirtualRun",
        "distance": 5000.0,
        "moving_time": 1800,
    }
    row = _parse_activity(activity)
    assert row["activity_type"] == "running"


def test_parse_laps_reads_from_icu_intervals_field():
    from sync.intervals_icu_sync import _parse_laps
    detail = _load_fixture("activity_i9000001_intervals.json")
    rows = _parse_laps("icu_i9000001", detail, activity_type="running")
    assert len(rows) == 3


def test_parse_laps_preserves_array_order():
    from sync.intervals_icu_sync import _parse_laps
    detail = _load_fixture("activity_i9000001_intervals.json")
    rows = _parse_laps("icu_i9000001", detail, activity_type="running")
    assert [r["split_num"] for r in rows] == ["1", "2", "3"]
    assert float(rows[1]["distance_km"]) == pytest.approx(5.0, abs=0.001)


def test_parse_laps_attaches_prefixed_activity_id():
    from sync.intervals_icu_sync import _parse_laps
    detail = _load_fixture("activity_i9000001_intervals.json")
    rows = _parse_laps("icu_i9000001", detail, activity_type="running")
    for row in rows:
        assert row["activity_id"] == "icu_i9000001"


def test_parse_laps_doubles_cadence_for_run():
    from sync.intervals_icu_sync import _parse_laps
    detail = _load_fixture("activity_i9000001_intervals.json")
    rows = _parse_laps("icu_i9000001", detail, activity_type="running")
    # interval 1 cadence=86.0 single-leg -> 172 double-leg spm
    assert float(rows[0]["avg_cadence"]) == pytest.approx(172.0, abs=0.1)


def test_parse_laps_leaves_elevation_change_empty():
    """icu_intervals has no per-interval elevation fields — leave empty."""
    from sync.intervals_icu_sync import _parse_laps
    detail = _load_fixture("activity_i9000001_intervals.json")
    rows = _parse_laps("icu_i9000001", detail, activity_type="running")
    for row in rows:
        assert row["elevation_change_m"] in (None, "")


def test_parse_laps_handles_single_interval_null_power():
    from sync.intervals_icu_sync import _parse_laps
    detail = _load_fixture("activity_i9000002_intervals.json")
    rows = _parse_laps("icu_i9000002", detail, activity_type="running")
    assert len(rows) == 1
    assert rows[0]["avg_power"] in (None, "")


def test_parse_laps_returns_empty_when_no_intervals():
    from sync.intervals_icu_sync import _parse_laps
    assert _parse_laps("icu_zzz", {"id": "zzz"}, activity_type="running") == []
    assert _parse_laps("icu_zzz", {"icu_intervals": []}, activity_type="running") == []


def test_parse_wellness_maps_date_and_fields():
    from sync.intervals_icu_sync import _parse_wellness
    wellness = _load_fixture("wellness.json")
    rows = _parse_wellness(wellness)
    assert len(rows) == 5
    first = rows[0]
    assert first["date"] == "2026-04-16"
    assert float(first["readiness_score"]) == 82
    assert float(first["hrv_avg"]) == 64.2
    assert float(first["resting_hr"]) == 48
    assert float(first["sleep_score"]) == 85
    assert float(first["total_sleep_sec"]) == 27900
    # intervals.icu does not expose these
    assert first.get("deep_sleep_sec") in (None, "")
    assert first.get("rem_sleep_sec") in (None, "")
    assert first.get("body_temp_delta") in (None, "")
    assert first["source"] == "intervals_icu"


def test_parse_thresholds_extracts_run_sport_settings():
    from sync.intervals_icu_sync import _parse_thresholds
    profile = _load_fixture("athlete_profile.json")
    today = date(2026, 4, 22)
    rows = _parse_thresholds(profile, today)
    metrics = {r["metric_type"]: r for r in rows}
    assert "running_ftp" in metrics
    assert float(metrics["running_ftp"]["value"]) == 270
    assert "lthr" in metrics
    assert float(metrics["lthr"]["value"]) == 168
    # threshold_pace in m/s (V2 verified). Fixture 4.08163 m/s -> ~245.0 sec/km.
    assert "threshold_pace_sec_km" in metrics
    assert float(metrics["threshold_pace_sec_km"]["value"]) == pytest.approx(245.0, abs=0.5)
    assert "max_hr" in metrics
    assert float(metrics["max_hr"]["value"]) == 192
    for row in rows:
        assert row["date"] == "2026-04-22"
        assert row["source"] == "intervals_icu"


def test_parse_thresholds_converts_threshold_pace_from_mps():
    """intervals.icu returns threshold_pace in m/s; Praxys stores sec/km."""
    from sync.intervals_icu_sync import _parse_thresholds
    profile = {
        "sportSettings": [{
            "types": ["Run"],
            "ftp": 270, "lthr": 168, "max_hr": 192,
            "threshold_pace": 4.2918453,  # m/s -> 1000/4.29 ~= 233.0 sec/km
        }],
    }
    rows = _parse_thresholds(profile, date(2026, 4, 22))
    metric = {r["metric_type"]: r for r in rows}
    assert float(metric["threshold_pace_sec_km"]["value"]) == pytest.approx(233.0, abs=0.5)


def test_parse_thresholds_skips_null_ftp():
    """When sportSettings has ftp=None, do not emit a running_ftp row."""
    from sync.intervals_icu_sync import _parse_thresholds
    profile = {
        "sportSettings": [{
            "types": ["Run"],
            "ftp": None, "lthr": 168, "max_hr": 192,
            "threshold_pace": 4.08,
        }],
    }
    rows = _parse_thresholds(profile, date(2026, 4, 22))
    metric_types = {r["metric_type"] for r in rows}
    assert "running_ftp" not in metric_types
    assert "lthr" in metric_types


def test_parse_thresholds_ignores_sport_settings_without_run():
    """If only Ride sportSettings exist, no threshold rows are emitted."""
    from sync.intervals_icu_sync import _parse_thresholds
    profile = {
        "id": "i123456",
        "sportSettings": [{"types": ["Ride"], "ftp": 290, "lthr": 170}],
    }
    rows = _parse_thresholds(profile, date(2026, 4, 22))
    assert rows == []


@patch("sync.intervals_icu_sync._request")
def test_fetch_activities_api_uses_date_window_params(mock_req):
    from sync.intervals_icu_sync import fetch_activities_api
    mock_req.return_value = []
    creds = {"athlete_id": "i123456", "api_key": "k"}
    fetch_activities_api(creds, from_date="2026-04-01", to_date="2026-04-22")
    path = mock_req.call_args.args[0]
    params = mock_req.call_args.kwargs["params"]
    assert path == "/athlete/i123456/activities"
    assert params["oldest"] == "2026-04-01"
    assert params["newest"] == "2026-04-22"


@patch("sync.intervals_icu_sync._request")
def test_fetch_activities_api_returns_parsed_rows(mock_req):
    from sync.intervals_icu_sync import fetch_activities_api
    mock_req.return_value = _load_fixture("activities.json")
    creds = {"athlete_id": "i123456", "api_key": "k"}
    rows, raw = fetch_activities_api(creds, from_date="2026-04-01")
    assert len(rows) == 2
    assert rows[0]["activity_id"] == "icu_i9000001"
    assert len(raw) == 2
    assert raw[0]["id"] == "i9000001"


@patch("sync.intervals_icu_sync._request")
def test_fetch_activity_laps_uses_intervals_param(mock_req):
    """V3 verified: lap data via ?intervals=true, response field icu_intervals."""
    from sync.intervals_icu_sync import fetch_activity_laps
    mock_req.return_value = _load_fixture("activity_i9000001_intervals.json")
    creds = {"athlete_id": "i123456", "api_key": "k"}
    rows = fetch_activity_laps("i9000001", creds, activity_type="running")
    path = mock_req.call_args.args[0]
    params = mock_req.call_args.kwargs["params"]
    assert path == "/activity/i9000001"
    assert params == {"intervals": "true"}
    assert len(rows) == 3


@patch("sync.intervals_icu_sync._request")
def test_fetch_wellness_api(mock_req):
    from sync.intervals_icu_sync import fetch_wellness_api
    mock_req.return_value = _load_fixture("wellness.json")
    creds = {"athlete_id": "i123456", "api_key": "k"}
    rows = fetch_wellness_api(creds, from_date="2026-04-16", to_date="2026-04-20")
    path = mock_req.call_args.args[0]
    assert path == "/athlete/i123456/wellness"
    assert len(rows) == 5


@patch("sync.intervals_icu_sync._request")
def test_fetch_athlete_profile_api(mock_req):
    from sync.intervals_icu_sync import fetch_athlete_profile_api
    mock_req.return_value = _load_fixture("athlete_profile.json")
    creds = {"athlete_id": "i123456", "api_key": "k"}
    profile = fetch_athlete_profile_api(creds)
    path = mock_req.call_args.args[0]
    assert path == "/athlete/i123456"
    assert profile["id"] == "i123456"
    assert len(profile["sportSettings"]) == 2
