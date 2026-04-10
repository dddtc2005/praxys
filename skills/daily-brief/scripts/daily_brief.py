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
from api.views import last_activity, upcoming_workouts, week_load, science_context  # noqa: E402


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
        "science": science_context(data.get("science", {})),
        "last_activity": last_activity(data.get("activities", [])),
        "upcoming_workouts": upcoming_workouts(plan_df),
        "week_load": week_load(data.get("weekly_review", {})),
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
