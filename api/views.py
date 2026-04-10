"""Shared view-model helpers for API routes and CLI scripts.

These functions extract presentation-ready data from get_dashboard_data().
Both web API routes and CLI skill scripts import from here to stay in sync.
"""
from datetime import date

import pandas as pd


def last_activity(activities: list[dict]) -> dict | None:
    """Extract the most recent activity summary."""
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


def upcoming_workouts(plan_df: pd.DataFrame, limit: int = 3) -> list[dict]:
    """Extract next N planned workouts after today."""
    if plan_df is None or plan_df.empty:
        return []
    if "date" not in plan_df.columns:
        return []
    today_str = date.today().isoformat()
    df = plan_df.copy()
    df["_date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["_date"])
    if df.empty:
        return []
    df["date_str"] = df["_date"].dt.strftime("%Y-%m-%d")
    future = df[df["date_str"] > today_str].sort_values("date_str").head(limit)
    result = []
    for _, row in future.iterrows():
        dur = row.get("planned_duration_min") or row.get("duration_min")
        result.append({
            "date": row["date_str"],
            "workout_type": str(row.get("workout_type", "")),
            "duration_min": float(dur) if dur is not None and dur == dur else None,
            "description": str(row.get("workout_description", "")),
        })
    return result


def week_load(weekly_review: dict) -> dict | None:
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


def science_context(science: dict) -> dict:
    """Extract active science theory metadata for display.

    Returns a dict with theory name, simple description, and key citation
    for each active pillar. Used to show methodology in both web and CLI.
    """
    result: dict = {}
    for pillar in ("load", "recovery", "prediction", "zones"):
        theory = science.get(pillar)
        if theory is None:
            continue
        citations = []
        for c in getattr(theory, "citations", []):
            cite = {"title": c.title}
            if c.year:
                cite["year"] = c.year
            if getattr(c, "url", None):
                cite["url"] = c.url
            citations.append(cite)
        result[pillar] = {
            "id": theory.id,
            "name": theory.name,
            "simple_description": theory.simple_description,
            "citations": citations,
        }
    return result


def fitness_summary(fitness_fatigue: dict) -> dict:
    """Extract latest CTL/ATL/TSB values from fitness_fatigue arrays."""
    ctl = fitness_fatigue.get("ctl", [])
    atl = fitness_fatigue.get("atl", [])
    tsb = fitness_fatigue.get("tsb", [])
    return {
        "ctl": ctl[-1] if ctl else None,
        "atl": atl[-1] if atl else None,
        "tsb": tsb[-1] if tsb else None,
    }
