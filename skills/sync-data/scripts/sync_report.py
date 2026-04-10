#!/usr/bin/env python3
"""Sync training data and output a structured JSON report.

Usage:
    python skills/sync-data/scripts/sync_report.py --pretty
    python skills/sync-data/scripts/sync_report.py --from-date 2025-01-01
    python skills/sync-data/scripts/sync_report.py --skip oura --pretty
"""
import argparse
import json
import os
import sys
import traceback
from collections.abc import Callable
from datetime import date, timedelta

# Project root is three levels up from this script.
_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _PROJECT_ROOT)

from dotenv import load_dotenv  # noqa: E402

from sync.csv_utils import read_csv  # noqa: E402


def _count_rows(csv_path: str) -> int:
    """Count rows in a CSV file (0 if missing)."""
    return len(read_csv(csv_path))


def _date_range(csv_path: str, date_col: str = "date") -> list[str]:
    """Return [min_date, max_date] from the last 30 rows of a CSV."""
    rows = read_csv(csv_path)
    if not rows:
        return []
    recent = rows[-30:]
    dates = sorted(set(r.get(date_col, "")[:10] for r in recent if r.get(date_col)))
    if not dates:
        return []
    return [dates[0], dates[-1]]


def _sync_source(
    sync_fn: Callable[[str, str | None], None],
    data_dir: str,
    csv_files: list[str],
    from_date: str | None,
) -> dict:
    """Run sync for one source, capturing before/after row counts."""
    before_counts = {f: _count_rows(os.path.join(data_dir, f)) for f in csv_files}
    total_before = sum(before_counts.values())

    try:
        sync_fn(data_dir, from_date)
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        return {"status": "error", "error_type": type(e).__name__, "reason": str(e)}

    after_counts = {f: _count_rows(os.path.join(data_dir, f)) for f in csv_files}
    total_after = sum(after_counts.values())

    # Get date range from the primary CSV (first in list)
    primary = os.path.join(data_dir, csv_files[0])
    dr = _date_range(primary)

    return {
        "status": "ok",
        "rows_before": total_before,
        "rows_after": total_after,
        "new_rows": total_after - total_before,
        "date_range": dr,
        "files": [f"data/{f}" for f in csv_files],
    }


def main() -> None:
    env_path = os.path.join(_PROJECT_ROOT, "sync", ".env")
    env_loaded = load_dotenv(env_path)

    parser = argparse.ArgumentParser(description="Sync training data with JSON report")
    parser.add_argument("--from-date", help="Start date (YYYY-MM-DD) for backfill")
    parser.add_argument("--skip", nargs="*", default=[], help="Sources to skip")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    data_dir = os.path.join(_PROJECT_ROOT, "data")
    skip = [s.lower() for s in args.skip]
    from_date = args.from_date

    result: dict = {
        "sources": {},
        "sync_date": date.today().isoformat(),
        "from_date": from_date or (date.today() - timedelta(days=7)).isoformat(),
    }
    if not env_loaded:
        result["env_hint"] = "No sync/.env file found. Run the setup skill to configure data sources."

    # --- Oura ---
    if "oura" in skip:
        result["sources"]["oura"] = {"status": "user_skipped"}
    else:
        token = os.environ.get("OURA_TOKEN")
        if not token:
            result["sources"]["oura"] = {"status": "skipped", "reason": "OURA_TOKEN not set"}
        else:
            from sync.oura_sync import sync as oura_sync

            def _oura(data_dir, from_date):
                oura_sync(token, data_dir, from_date)

            result["sources"]["oura"] = _sync_source(
                _oura, data_dir,
                ["oura/sleep.csv", "oura/readiness.csv"],
                from_date,
            )

    # --- Garmin ---
    if "garmin" in skip:
        result["sources"]["garmin"] = {"status": "user_skipped"}
    else:
        email = os.environ.get("GARMIN_EMAIL")
        password = os.environ.get("GARMIN_PASSWORD")
        if not email or not password:
            result["sources"]["garmin"] = {
                "status": "skipped",
                "reason": "GARMIN_EMAIL or GARMIN_PASSWORD not set",
            }
        else:
            from sync.garmin_sync import sync as garmin_sync

            is_cn = os.environ.get("GARMIN_IS_CN", "").lower() == "true"

            def _garmin(data_dir, from_date):
                garmin_sync(email, password, data_dir, from_date, is_cn=is_cn)

            result["sources"]["garmin"] = _sync_source(
                _garmin, data_dir,
                [
                    "garmin/activities.csv",
                    "garmin/activity_splits.csv",
                    "garmin/daily_metrics.csv",
                    "garmin/lactate_threshold.csv",
                ],
                from_date,
            )

    # --- Stryd ---
    if "stryd" in skip:
        result["sources"]["stryd"] = {"status": "user_skipped"}
    else:
        stryd_email = os.environ.get("STRYD_EMAIL")
        stryd_password = os.environ.get("STRYD_PASSWORD")
        if not stryd_email or not stryd_password:
            result["sources"]["stryd"] = {
                "status": "skipped",
                "reason": "STRYD_EMAIL or STRYD_PASSWORD not set",
            }
        else:
            from sync.stryd_sync import sync as stryd_sync

            def _stryd(data_dir, from_date):
                stryd_sync(data_dir, email=stryd_email, password=stryd_password, from_date=from_date)

            result["sources"]["stryd"] = _sync_source(
                _stryd, data_dir,
                [
                    "stryd/power_data.csv",
                    "stryd/activity_splits.csv",
                    "stryd/training_plan.csv",
                ],
                from_date,
            )

    indent = 2 if args.pretty else None
    json.dump(result, sys.stdout, indent=indent, default=str)
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
