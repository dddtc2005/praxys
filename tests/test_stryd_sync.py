from unittest.mock import MagicMock, patch

import pytest
import requests

from sync.stryd_sync import (
    _workout_type_from_name,
    fetch_activities_api,
    fetch_training_plan_api,
    sync,
)


def test_workout_type_from_name():
    assert _workout_type_from_name("Day 46 - Steady Aerobic") == "steady aerobic"
    assert _workout_type_from_name("Day 48 - Long") == "long"
    assert _workout_type_from_name("Day 47 - Recovery") == "recovery"
    assert _workout_type_from_name("Custom Name") == "custom name"


# --- Helpers for mocking ---

def _mock_login_response(user_id="user-123", token="tok-abc"):
    resp = MagicMock()
    resp.json.return_value = {"id": user_id, "token": token}
    resp.raise_for_status = MagicMock()
    return resp


def _mock_calendar_response(activities=None, workouts=None):
    resp = MagicMock()
    resp.json.return_value = {
        "activities": activities or [],
        "workouts": workouts or [],
    }
    resp.raise_for_status = MagicMock()
    return resp


def _mock_401_response():
    resp = MagicMock()
    resp.status_code = 401
    error = requests.HTTPError(response=resp)
    return error


# --- sync() derives user_id from login API ---

@patch("sync.stryd_sync._fetch_stryd_splits", return_value=[])
@patch("sync.stryd_sync.append_rows")
@patch("sync.stryd_sync.requests")
def test_sync_derives_user_id_from_login(mock_requests, mock_append, mock_splits):
    """sync() should use the user_id returned by _login_api(), not require it as a param."""
    activity = {
        "start_time": 1700000000,
        "distance": 5000,
        "moving_time": 1500,
        "average_power": 240,
        "stress": 55,
    }
    mock_requests.post.return_value = _mock_login_response(user_id="derived-id")
    mock_requests.get.return_value = _mock_calendar_response(activities=[activity])
    mock_requests.HTTPError = requests.HTTPError

    sync("/tmp/data", email="a@b.com", password="pw", from_date="2024-01-01")

    # Verify the calendar API was called with the derived user_id
    get_calls = mock_requests.get.call_args_list
    assert len(get_calls) >= 1
    first_url = get_calls[0][1].get("url", get_calls[0][0][0] if get_calls[0][0] else "")
    assert "derived-id" in first_url


# --- sync() retries activities on 401 ---

@patch("sync.stryd_sync._fetch_stryd_splits", return_value=[])
@patch("sync.stryd_sync.append_rows")
@patch("sync.stryd_sync.requests")
def test_sync_retries_activities_on_401(mock_requests, mock_append, mock_splits):
    """Activity fetch should re-login and retry once on 401."""
    activity = {
        "start_time": 1700000000,
        "distance": 5000,
        "moving_time": 1500,
        "average_power": 240,
    }

    mock_requests.post.return_value = _mock_login_response()
    mock_requests.HTTPError = requests.HTTPError

    # First GET raises 401, second succeeds
    error_401 = _mock_401_response()
    success_resp = _mock_calendar_response(activities=[activity])
    mock_requests.get.side_effect = [
        requests.HTTPError(response=MagicMock(status_code=401)),
        success_resp,  # retry for activities
        _mock_calendar_response(),  # training plan
    ]
    # raise_for_status on success should not raise
    success_resp.raise_for_status = MagicMock()

    # Need to make the first get call raise on raise_for_status
    first_resp = MagicMock()
    first_resp.raise_for_status.side_effect = requests.HTTPError(
        response=MagicMock(status_code=401)
    )
    success_activities = _mock_calendar_response(activities=[activity])
    success_plan = _mock_calendar_response()

    mock_requests.get.side_effect = [first_resp, success_activities, success_plan]

    sync("/tmp/data", email="a@b.com", password="pw", from_date="2024-01-01")

    # Should have called login twice (initial + retry)
    assert mock_requests.post.call_count == 2


# --- sync() retries training plan on 401 ---

@patch("sync.stryd_sync._fetch_stryd_splits", return_value=[])
@patch("sync.stryd_sync.append_rows")
@patch("sync.stryd_sync.requests")
def test_sync_retries_training_plan_on_401(mock_requests, mock_append, mock_splits):
    """Training plan fetch should re-login and retry once on 401."""
    mock_requests.post.return_value = _mock_login_response()
    mock_requests.HTTPError = requests.HTTPError

    activities_resp = _mock_calendar_response()  # no activities, fine

    plan_fail = MagicMock()
    plan_fail.raise_for_status.side_effect = requests.HTTPError(
        response=MagicMock(status_code=401)
    )
    plan_success = _mock_calendar_response()

    mock_requests.get.side_effect = [activities_resp, plan_fail, plan_success]

    sync("/tmp/data", email="a@b.com", password="pw", from_date="2024-01-01")

    # Should have called login twice (initial + retry for plan)
    assert mock_requests.post.call_count == 2


# --- sync() skips when credentials missing ---

@patch("sync.stryd_sync.requests")
def test_sync_skips_without_credentials(mock_requests):
    """sync() should skip gracefully when email/password not provided."""
    sync("/tmp/data", email=None, password=None)
    mock_requests.post.assert_not_called()


# --- fetch_training_plan_api parses power targets ---

@patch("sync.stryd_sync.requests.get")
def test_fetch_training_plan_parses_power_targets(mock_get):
    """Training plan should convert CP percentage targets to absolute watts."""
    workout = {
        "deleted": False,
        "date": "2026-04-04T02:00:00Z",
        "duration": 3600,
        "distance": 10000,
        "workout": {
            "title": "Day 10 - Threshold",
            "type": "threshold",
            "blocks": [
                {
                    "repeat": 1,
                    "segments": [
                        {
                            "intensity_class": "work",
                            "intensity_percent": {"min": 95, "max": 105},
                            "duration_time": {"minute": 20},
                        }
                    ],
                }
            ],
        },
    }
    mock_get.return_value = MagicMock(
        json=MagicMock(return_value={"workouts": [workout]}),
        raise_for_status=MagicMock(),
    )

    rows = fetch_training_plan_api("user-1", "tok", cp_watts=250.0)

    assert len(rows) == 1
    assert rows[0]["target_power_min"] == "238"  # round(250 * 95 / 100)
    assert rows[0]["target_power_max"] == "262"  # round(250 * 105 / 100) = 262 (banker's rounding)
    assert rows[0]["workout_type"] == "threshold"
