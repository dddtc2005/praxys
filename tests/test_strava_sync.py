from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from sync.strava_sync import (
    DEFAULT_SCOPE,
    STRAVA_ACTIVITIES_API,
    STRAVA_ACTIVITY_LAPS_API,
    STRAVA_AUTHORIZE_URL,
    build_authorize_url,
    fetch_activities_api,
    fetch_activity_laps,
    refresh_access_token_if_needed,
)


def _mock_response(payload):
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def test_build_authorize_url_includes_expected_query_params():
    url = build_authorize_url(
        "12345",
        "https://api.example.test/callback",
        "signed-state-token",
    )

    assert url.startswith(f"{STRAVA_AUTHORIZE_URL}?")
    assert "client_id=12345" in url
    assert "redirect_uri=https%3A%2F%2Fapi.example.test%2Fcallback" in url
    assert "response_type=code" in url
    assert "approval_prompt=auto" in url
    assert "scope=read%2Cactivity%3Aread_all%2Cprofile%3Aread_all" in url
    assert "state=signed-state-token" in url


@patch("sync.strava_sync.requests.post")
def test_refresh_access_token_skips_valid_token(mock_post):
    now = datetime(2026, 4, 21, 9, 0, 0, tzinfo=timezone.utc)
    credentials = {
        "access_token": "still-valid",
        "refresh_token": "refresh-1",
        "expires_at": int(now.timestamp()) + 3601,
    }

    updated, changed = refresh_access_token_if_needed(
        credentials,
        "client-id",
        "client-secret",
        now=now,
    )

    assert updated is credentials
    assert changed is False
    mock_post.assert_not_called()


@patch("sync.strava_sync.requests.post")
def test_refresh_access_token_refreshes_and_rotates_tokens(mock_post):
    now = datetime(2026, 4, 21, 9, 0, 0, tzinfo=timezone.utc)
    credentials = {
        "access_token": "expired-token",
        "refresh_token": "refresh-1",
        "expires_at": int(now.timestamp()) + 600,
        "athlete": {"id": 10},
    }
    mock_post.return_value = _mock_response(
        {
            "access_token": "fresh-token",
            "refresh_token": "refresh-2",
            "expires_at": int(now.timestamp()) + 7200,
            "expires_in": 7200,
            "athlete": {"id": 11, "username": "runner"},
        }
    )

    updated, changed = refresh_access_token_if_needed(
        credentials,
        "client-id",
        "client-secret",
        now=now,
    )

    assert changed is True
    assert updated == {
        "access_token": "fresh-token",
        "refresh_token": "refresh-2",
        "expires_at": int(now.timestamp()) + 7200,
        "expires_in": 7200,
        "athlete": {"id": 11, "username": "runner"},
    }
    mock_post.assert_called_once_with(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": "client-id",
            "client_secret": "client-secret",
            "grant_type": "refresh_token",
            "refresh_token": "refresh-1",
        },
        timeout=30,
    )


def test_refresh_access_token_requires_refresh_token():
    now = datetime(2026, 4, 21, 9, 0, 0, tzinfo=timezone.utc)

    with pytest.raises(RuntimeError, match="missing refresh_token"):
        refresh_access_token_if_needed(
            {"access_token": "expired", "expires_at": int(now.timestamp())},
            "client-id",
            "client-secret",
            now=now,
        )


@patch("sync.strava_sync.requests.get")
def test_fetch_activities_api_paginates_and_parses_rows(mock_get):
    mock_get.side_effect = [
        _mock_response(
            [
                {
                    "id": 101,
                    "start_date": "2026-04-01T05:00:00Z",
                    "start_date_local": "2026-04-01T13:00:00Z",
                    "sport_type": "Run",
                    "distance": 10000.0,
                    "moving_time": 3000,
                    "average_watts": 245.4,
                    "max_watts": 410,
                    "average_heartrate": 150.2,
                    "max_heartrate": 172,
                    "average_cadence": 176.6,
                    "total_elevation_gain": 88.8,
                },
                {
                    "id": 102,
                    "start_date": "2026-04-02T05:15:00Z",
                    "start_date_local": "2026-04-02T13:15:00Z",
                    "sport_type": "TrailRun",
                    "distance": 15000.0,
                    "elapsed_time": 5400,
                },
            ]
        ),
        _mock_response(
            [
                {
                    "id": 103,
                    "start_date": "2026-04-03T05:30:00Z",
                    "start_date_local": "2026-04-03T13:30:00Z",
                    "type": "Workout",
                    "distance": 0,
                    "moving_time": 1800,
                }
            ]
        ),
    ]

    rows, raw = fetch_activities_api(
        "access-token",
        "2026-04-01",
        "2026-04-03",
        page_size=2,
    )

    assert len(rows) == 3
    assert len(raw) == 3

    assert rows[0] == {
        "activity_id": "101",
        "date": "2026-04-01",
        "start_time": "2026-04-01T05:00:00Z",
        "activity_type": "running",
        "distance_km": "10.0",
        "duration_sec": "3000.0",
        "avg_power": "245.4",
        "max_power": "410.0",
        "avg_hr": "150.2",
        "max_hr": "172.0",
        "avg_pace_sec_km": "300.0",
        "elevation_gain_m": "88.8",
        "avg_cadence": "176.6",
        "source": "strava",
    }
    assert rows[1]["activity_type"] == "trail_running"
    assert rows[1]["duration_sec"] == "5400.0"
    assert rows[2]["activity_type"] == "strength"
    assert rows[2]["distance_km"] == ""
    assert rows[2]["avg_pace_sec_km"] == ""

    first_call = mock_get.call_args_list[0]
    assert first_call.args[0] == STRAVA_ACTIVITIES_API
    assert first_call.kwargs["headers"] == {"Authorization": "Bearer access-token"}
    assert first_call.kwargs["params"] == {
        "after": 1775001600,
        "before": 1775260799,
        "page": 1,
        "per_page": 2,
    }

    second_call = mock_get.call_args_list[1]
    assert second_call.kwargs["params"]["page"] == 2


@patch("sync.strava_sync.requests.get")
def test_fetch_activity_laps_parses_split_metrics(mock_get):
    mock_get.return_value = _mock_response(
        [
            {
                "distance": 1000.0,
                "moving_time": 285,
                "average_watts": 302.4,
                "average_heartrate": 151.2,
                "max_heartrate": 160.7,
                "average_cadence": 178.1,
                "total_elevation_gain": 4.8,
            },
            {
                "distance": 0,
                "elapsed_time": 90,
            },
        ]
    )

    rows = fetch_activity_laps("4242", "access-token")

    assert rows == [
        {
            "activity_id": "4242",
            "split_num": "1",
            "distance_km": "1.0",
            "duration_sec": "285.0",
            "avg_power": "302.4",
            "avg_hr": "151.2",
            "max_hr": "160.7",
            "avg_cadence": "178.1",
            "avg_pace_sec_km": "285.0",
            "elevation_change_m": "4.8",
        },
        {
            "activity_id": "4242",
            "split_num": "2",
            "distance_km": "0.0",
            "duration_sec": "90.0",
            "avg_power": "",
            "avg_hr": "",
            "max_hr": "",
            "avg_cadence": "",
            "avg_pace_sec_km": "",
            "elevation_change_m": "",
        },
    ]
    mock_get.assert_called_once_with(
        STRAVA_ACTIVITY_LAPS_API.format(activity_id="4242"),
        headers={"Authorization": "Bearer access-token"},
        timeout=30,
    )


def test_default_scope_matches_activities_only_oauth_contract():
    assert DEFAULT_SCOPE == "read,activity:read_all,profile:read_all"
