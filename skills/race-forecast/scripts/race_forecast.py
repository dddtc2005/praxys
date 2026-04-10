#!/usr/bin/env python3
"""Output race prediction and goal feasibility as JSON.

Includes: predicted race time, goal comparison, required CP/pace,
threshold trend, and days to race.

Usage:
    python skills/race-forecast/scripts/race_forecast.py --pretty
"""
import argparse
import json
import sys
import os
import traceback
from datetime import date

# Project root is three levels up from this script.
_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _PROJECT_ROOT)

from api.deps import get_dashboard_data  # noqa: E402
from api.views import fitness_summary, science_context  # noqa: E402
from analysis.config import load_config  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Output race forecast as JSON")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    data = get_dashboard_data()
    config = load_config()

    output = {
        "date": date.today().isoformat(),
        "training_base": data["training_base"],
        "display": data["display"],
        "latest_threshold": data.get("latest_cp"),
        "threshold_trend": data.get("cp_trend_data"),
        "race_countdown": data.get("race_countdown"),
        "goal": {
            "distance": config.goal.get("distance", "marathon"),
            "race_date": config.goal.get("race_date", ""),
            "target_time_sec": config.goal.get("target_time_sec")
                or config.goal.get("race_target_time_sec"),
        },
        "science": science_context(data.get("science", {})),
        "fitness_snapshot": fitness_summary(data.get("fitness_fatigue", {})),
    }

    indent = 2 if args.pretty else None
    json.dump(output, sys.stdout, indent=indent, default=str)
    if indent:
        sys.stdout.write("\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        json.dump({"error": True, "error_type": type(e).__name__, "message": str(e)},
                  sys.stdout, indent=2)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
