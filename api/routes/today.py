"""Today's training signal endpoint."""
from datetime import date, timedelta

import pandas as pd
from fastapi import APIRouter

from api.deps import get_dashboard_data

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


def _last_activity(activities: list[dict]) -> dict | None:
    """Find the most recent activity."""
    if not activities:
        return None
    act = activities[0]  # already sorted descending by date
    if not act.get("date"):
        return None
    return {
        "date": act["date"],
        "activity_type": act.get("activity_type", ""),
        "distance_km": act.get("distance_km"),
        "duration_sec": act.get("duration_sec"),
        "avg_power": act.get("avg_power"),
        "avg_pace_min_km": act.get("avg_pace_min_km"),
        "rss": act.get("rss"),
    }


def _week_load(weekly_review: dict) -> dict | None:
    """Extract current week load vs plan."""
    weeks = weekly_review.get("weeks", [])
    actual = weekly_review.get("actual_rss", [])
    planned = weekly_review.get("planned_rss", [])
    if not weeks or not actual:
        return None
    return {
        "week_label": weeks[-1],
        "actual": actual[-1] if actual else 0,
        "planned": planned[-1] if planned else None,
    }


def _upcoming_workouts(plan_df: pd.DataFrame, limit: int = 3) -> list[dict]:
    """Extract next N planned workouts after today."""
    if plan_df is None or plan_df.empty:
        return []
    today_str = date.today().isoformat()
    if "date" not in plan_df.columns:
        return []
    df = plan_df.copy()
    df["_date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["_date"])
    if df.empty:
        return []
    df["date_str"] = df["_date"].dt.strftime("%Y-%m-%d")
    future = df[df["date_str"] > today_str].sort_values("date_str").head(limit)
    result = []
    for _, row in future.iterrows():
        dur = row.get("planned_duration_min")
        if dur is None or (isinstance(dur, float) and dur != dur):  # NaN check
            dur = row.get("duration_min")
        result.append({
            "date": row["date_str"],
            "workout_type": str(row.get("workout_type", "")),
            "duration_min": dur if dur is not None and dur == dur else None,
        })
    return result


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
        "last_activity": _last_activity(activities),
        "week_load": _week_load(weekly_review),
        "upcoming": _upcoming_workouts(plan_df),
    }
