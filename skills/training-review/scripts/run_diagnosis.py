#!/usr/bin/env python3
"""Output training diagnosis as JSON.

Includes: volume analysis, consistency, interval intensity, zone distribution,
findings, suggestions, CP trend, and fitness/fatigue summary.

Usage:
    python skills/training-review/scripts/run_diagnosis.py --pretty
"""
import argparse
import json
import sys
import os
from datetime import date

# Project root is three levels up from this script.
_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _PROJECT_ROOT)

from api.deps import get_dashboard_data  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Output training diagnosis as JSON")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    data = get_dashboard_data()

    # Fitness/fatigue summary (latest values, not full chart arrays)
    ff = data.get("fitness_fatigue", {})
    ctl_values = ff.get("ctl", [])
    atl_values = ff.get("atl", [])
    tsb_values = ff.get("tsb", [])

    output = {
        "date": date.today().isoformat(),
        "training_base": data["training_base"],
        "display": data["display"],
        "latest_threshold": data.get("latest_cp"),
        "threshold_trend": data.get("cp_trend_data"),
        "diagnosis": data.get("diagnosis", {}),
        "fitness_summary": {
            "ctl": ctl_values[-1] if ctl_values else None,
            "atl": atl_values[-1] if atl_values else None,
            "tsb": tsb_values[-1] if tsb_values else None,
        },
        "weekly_review": data.get("weekly_review", {}),
        "workout_flags": data.get("workout_flags", []),
    }

    indent = 2 if args.pretty else None
    json.dump(output, sys.stdout, indent=indent, default=str)
    if indent:
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
