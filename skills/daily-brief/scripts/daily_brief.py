#!/usr/bin/env python3
"""Output today's training brief as JSON.

Includes: training signal, recovery status, upcoming workouts,
last activity summary, and weekly load comparison.

Usage:
    python skills/daily-brief/scripts/daily_brief.py --pretty
"""
import argparse
import json
import sys
import os
from datetime import date

import pandas as pd

# Project root is three levels up from this script.
_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _PROJECT_ROOT)

from api.deps import get_dashboard_data  # noqa: E402


def _last_activity(activities: list[dict]) -> dict | None:
    """Extract the most recent activity."""
    if not activities:
        return None
    act = activities[0]  # sorted descending by date
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


def _upcoming_workouts(plan_df: pd.DataFrame, limit: int = 3) -> list[dict]:
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


def _week_load(weekly_review: dict) -> dict | None:
    """Current week load vs plan."""
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


def _data_freshness(data_dir: str) -> dict:
    """Check the latest date in key CSV files to assess data staleness."""
    from sync.csv_utils import read_csv

    today_str = date.today().isoformat()
    sources = {
        "activities": "garmin/activities.csv",
        "recovery": "oura/readiness.csv",
        "power": "stryd/power_data.csv",
    }
    freshness: dict = {"today": today_str, "sources": {}}
    for key, csv_path in sources.items():
        full_path = os.path.join(data_dir, csv_path)
        rows = read_csv(full_path)
        if not rows:
            freshness["sources"][key] = {"latest_date": None, "stale": True}
            continue
        dates = sorted(r.get("date", "")[:10] for r in rows if r.get("date"))
        latest = dates[-1] if dates else None
        freshness["sources"][key] = {
            "latest_date": latest,
            "stale": latest is None or latest < today_str,
        }
    freshness["any_stale"] = any(s["stale"] for s in freshness["sources"].values())
    return freshness


def main() -> None:
    parser = argparse.ArgumentParser(description="Output today's training brief as JSON")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    data = get_dashboard_data()
    plan_df = data.get("plan", pd.DataFrame())
    data_dir = os.path.join(_PROJECT_ROOT, "data")

    output = {
        "date": date.today().isoformat(),
        "data_freshness": _data_freshness(data_dir),
        "signal": data["signal"],
        "recovery_analysis": data.get("recovery_analysis"),
        "last_activity": _last_activity(data.get("activities", [])),
        "upcoming_workouts": _upcoming_workouts(plan_df),
        "week_load": _week_load(data.get("weekly_review", {})),
        "warnings": data.get("warnings", []),
        "training_base": data["training_base"],
        "display": data["display"],
    }

    indent = 2 if args.pretty else None
    json.dump(output, sys.stdout, indent=indent, default=str)
    if indent:
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
