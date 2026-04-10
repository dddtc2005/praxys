"""Today's training signal endpoint."""
import pandas as pd
from fastapi import APIRouter

from api.deps import get_dashboard_data
from api.views import last_activity, upcoming_workouts, week_load

router = APIRouter()


def _recovery_theory_meta(science: dict) -> dict | None:
    """Extract recovery theory metadata for the Today page."""
    theory = science.get("recovery")
    if theory is None:
        return None
    return {
        "id": theory.id,
        "name": theory.name,
        "simple_description": theory.simple_description,
        "params": theory.params,
    }


@router.get("/today")
def get_today():
    data = get_dashboard_data()
    science = data.get("science", {})
    activities = data.get("activities", [])
    weekly_review = data.get("weekly_review", {})
    plan_df = data.get("plan", pd.DataFrame())

    return {
        "signal": data["signal"],
        "tsb_sparkline": data["tsb_sparkline"],
        "warnings": data["warnings"],
        "training_base": data["training_base"],
        "display": data["display"],
        "recovery_theory": _recovery_theory_meta(science),
        "recovery_analysis": data.get("recovery_analysis"),
        "last_activity": last_activity(activities),
        "week_load": week_load(weekly_review),
        "upcoming": upcoming_workouts(plan_df),
    }
