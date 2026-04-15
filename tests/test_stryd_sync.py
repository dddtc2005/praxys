from unittest.mock import MagicMock, patch

import pytest
import requests

from sync.stryd_sync import (
    _workout_type_from_name,
    fetch_activities_api,
    fetch_training_plan_api,
)


def test_workout_type_from_name():
    assert _workout_type_from_name("Day 46 - Steady Aerobic") == "steady aerobic"
    assert _workout_type_from_name("Day 48 - Long") == "long"
    assert _workout_type_from_name("Day 47 - Recovery") == "recovery"
    assert _workout_type_from_name("Custom Name") == "custom name"


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
