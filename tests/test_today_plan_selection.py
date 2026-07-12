"""Regression tests for deterministic same-day workout selection."""
from datetime import date

import pandas as pd

from api.deps import _get_todays_plan


def test_todays_plan_selects_most_consequential_workout_regardless_of_order():
    """A duplicate rest/easy row cannot hide a same-day quality workout."""
    today = date(2026, 7, 12)
    rows = [
        {
            "date": today,
            "workout_type": "rest",
            "planned_duration_min": None,
            "source": "ai",
        },
        {
            "date": today,
            "workout_type": "easy",
            "planned_duration_min": 60,
            "source": "ai",
        },
        {
            "date": today,
            "workout_type": "threshold",
            "planned_duration_min": 45,
            "source": "ai",
        },
    ]

    for ordered in (rows, list(reversed(rows))):
        workout_type, detail = _get_todays_plan(pd.DataFrame(ordered), today)
        assert workout_type == "threshold"
        assert detail is not None
        assert detail["planned_duration_min"] == 45


def test_todays_plan_uses_duration_as_deterministic_hard_workout_tie_breaker():
    """When two demanding rows collide, select the larger planned session."""
    today = date(2026, 7, 12)
    plan = pd.DataFrame([
        {
            "date": today,
            "workout_type": "intervals",
            "planned_duration_min": 30,
            "source": pd.NA,
        },
        {
            "date": today,
            "workout_type": "long_run",
            "planned_duration_min": 120,
            "source": "ai",
        },
    ])

    workout_type, detail = _get_todays_plan(plan, today)

    assert workout_type == "long_run"
    assert detail is not None
    assert detail["planned_duration_min"] == 120