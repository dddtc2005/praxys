#!/usr/bin/env python3
"""Output training diagnosis as JSON.

Includes: volume analysis, consistency, interval intensity, zone distribution,
findings, suggestions, CP trend, and fitness/fatigue summary.

Usage:
    python scripts/run_diagnosis.py --pretty
"""
import argparse
import json
import sys
import os
import traceback
from datetime import date

# Project root is one level up from this script.
_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _PROJECT_ROOT)

from api.deps import get_dashboard_data  # noqa: E402
from api.views import fitness_summary, science_context  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Output training diagnosis as JSON")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    data = get_dashboard_data()

    output = {
        "date": date.today().isoformat(),
        "training_base": data["training_base"],
        "display": data["display"],
        "latest_threshold": data.get("latest_cp"),
        "threshold_trend": data.get("cp_trend_data"),
        "diagnosis": data.get("diagnosis", {}),
        "science": science_context(data.get("science", {})),
        "fitness_summary": fitness_summary(data.get("fitness_fatigue", {})),
        "weekly_review": data.get("weekly_review", {}),
        "workout_flags": data.get("workout_flags", []),
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
