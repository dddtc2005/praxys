"""Sync power and training plan data from Stryd via their calendar API.

To set up:
1. Add STRYD_EMAIL and STRYD_PASSWORD to .env
2. Run: python -m sync.stryd_sync

The user ID is automatically derived from the Stryd login API response.
"""
import argparse
import os
import re
from datetime import date, datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

from sync.csv_utils import append_rows


def _workout_type_from_name(name: str) -> str:
    """Extract workout type from Stryd plan name like 'Day 46 - Steady Aerobic'."""
    m = re.match(r"Day\s+\d+\s*-\s*(.+)", name)
    return m.group(1).strip().lower() if m else name.lower()


# --- API-based fetch ---

STRYD_LOGIN_URL = "https://www.stryd.com/b/email/signin"
STRYD_CALENDAR_API = "https://api.stryd.com/b/api/v1/users/{user_id}/calendar"


def _login_api(email: str, password: str) -> tuple[str, str]:
    """Login via Stryd API. Returns (user_id, token)."""
    print("  Logging in via Stryd API...")
    resp = requests.post(
        STRYD_LOGIN_URL,
        json={"email": email, "password": password},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    user_id = data.get("id", "")
    token = data.get("token", "")
    if not token:
        raise RuntimeError("Login succeeded but no token in response")
    print(f"  Login successful (user_id={user_id})")
    return user_id, token


def fetch_activities_api(
    user_id: str,
    token: str,
    from_date: str,
    to_date: str | None = None,
) -> list[dict]:
    """Fetch completed activities from the Stryd calendar API.

    Args:
        user_id: Stryd user UUID.
        token: Bearer token for Stryd API.
        from_date: Start date (YYYY-MM-DD).
        to_date: End date (YYYY-MM-DD), defaults to today.

    Returns:
        List of dicts matching power_data.csv schema.
    """
    start_dt = datetime.strptime(from_date, "%Y-%m-%d")
    end_dt = datetime.strptime(to_date, "%Y-%m-%d") if to_date else datetime.now()
    # Add a day to end to include activities on the end date
    end_dt = end_dt.replace(hour=23, minute=59, second=59)

    from_ts = int(start_dt.timestamp())
    to_ts = int(end_dt.timestamp())

    url = STRYD_CALENDAR_API.format(user_id=user_id)
    resp = requests.get(
        url,
        params={"from": from_ts, "to": to_ts, "include_deleted": "false"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    activities = data.get("activities", [])
    print(f"  API returned {len(activities)} activities")

    rows = []
    for act in activities:
        # Convert unix timestamp to local datetime using the activity's timezone
        tz_name = act.get("time_zone", "UTC")
        try:
            from zoneinfo import ZoneInfo
            local_tz = ZoneInfo(tz_name)
        except (ImportError, KeyError):
            local_tz = timezone.utc
        start_unix = act.get("start_time") or act.get("timestamp")
        if not start_unix:
            continue
        start_utc = datetime.fromtimestamp(start_unix, tz=timezone.utc)
        start_local = start_utc.astimezone(local_tz)

        distance_m = act.get("distance", 0) or 0
        distance_km = round(distance_m / 1000, 2)
        moving_time = act.get("moving_time") or act.get("elapsed_time")

        # Convert seconds_in_zones list to JSON string for CSV storage
        zones_list = act.get("seconds_in_zones")
        zones_str = str(zones_list) if zones_list else ""

        row = {
            "date": start_local.strftime("%Y-%m-%d"),
            "start_time": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "name": act.get("name", ""),
            "stryd_type": act.get("type", ""),
            "surface_type": act.get("surface_type", ""),
            "avg_power": _round_or_empty(act.get("average_power")),
            "max_power": _round_or_empty(act.get("max_power")),
            "avg_hr": _round_or_empty(act.get("average_heart_rate")),
            "max_hr": _round_or_empty(act.get("max_heart_rate")),
            "avg_cadence": _round_or_empty(act.get("average_cadence")),
            "avg_stride_length": _round_or_empty(act.get("average_stride_length"), 3),
            "avg_oscillation": _round_or_empty(act.get("average_oscillation")),
            "leg_spring_stiffness": _round_or_empty(act.get("average_leg_spring")),
            "ground_time_ms": _round_or_empty(act.get("average_ground_time")),
            "elevation_gain_m": _round_or_empty(act.get("total_elevation_gain")),
            "avg_speed_ms": _round_or_empty(act.get("average_speed"), 3),
            "rss": _round_or_empty(act.get("stress")),
            "lower_body_stress": _round_or_empty(act.get("lower_body_stress")),
            "cp_estimate": _round_or_empty(act.get("ftp")),
            "seconds_in_zones": zones_str,
            "temperature_c": _round_or_empty(act.get("temperature")),
            "humidity": _round_or_empty(act.get("humidity"), 3),
            "distance_km": str(distance_km),
            "duration_sec": str(moving_time) if moving_time is not None else "",
        }
        print(f"    {row['date']} — {row['avg_power']}W, {row['distance_km']}km, RSS={row['rss']}")
        rows.append(row)

    return rows


def fetch_training_plan_api(
    user_id: str,
    token: str,
    cp_watts: float | None = None,
    days_ahead: int = 14,
) -> list[dict]:
    """Fetch upcoming planned workouts from the Stryd calendar API.

    The API returns planned workouts under the 'workouts' key (separate from
    completed 'activities'). Each workout has structured blocks with segments
    containing intensity as CP percentage.

    Args:
        cp_watts: Current CP in watts (for converting % targets to absolute watts).
                  If None, power targets are omitted.
    """
    today = date.today()
    end = today + timedelta(days=days_ahead)

    from_ts = int(datetime.combine(today, datetime.min.time()).timestamp())
    to_ts = int(datetime.combine(end, datetime.max.time()).timestamp())

    url = STRYD_CALENDAR_API.format(user_id=user_id)
    resp = requests.get(
        url,
        params={"from": from_ts, "to": to_ts, "include_deleted": "false"},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    workouts = data.get("workouts", [])
    print(f"  Plan API returned {len(workouts)} planned workouts")

    rows = []
    for item in workouts:
        if item.get("deleted"):
            continue

        # Parse date from ISO format: "2026-04-04T02:00:00Z"
        date_str = item.get("date", "")
        try:
            workout_date = datetime.fromisoformat(date_str.replace("Z", "+00:00")).strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            continue

        workout_info = item.get("workout", {})
        title = workout_info.get("title", "")
        workout_type = workout_info.get("type", "") or _workout_type_from_name(title)

        # Total duration and distance from the top-level summary
        duration_sec = item.get("duration", 0) or 0
        duration_min = round(duration_sec / 60, 1) if duration_sec else ""

        distance_m = item.get("distance", 0) or 0
        distance_km = round(distance_m / 1000, 1) if distance_m else ""

        # Extract power targets from the "work" segment blocks
        # Intensity is specified as percentage of CP
        power_min = ""
        power_max = ""
        blocks = workout_info.get("blocks", [])
        for block in blocks:
            for seg in block.get("segments", []):
                if seg.get("intensity_class") == "work":
                    pct = seg.get("intensity_percent", {})
                    pct_min = pct.get("min", 0)
                    pct_max = pct.get("max", 0)
                    if cp_watts and pct_min and pct_max:
                        power_min = str(round(cp_watts * pct_min / 100))
                        power_max = str(round(cp_watts * pct_max / 100))
                    break
            if power_min:
                break

        # Build workout description from blocks
        desc_parts = []
        for block in blocks:
            repeat = block.get("repeat", 1)
            for seg in block.get("segments", []):
                cls = seg.get("intensity_class", "")
                dur = seg.get("duration_time", {})
                dur_str = ""
                if dur.get("hour"):
                    dur_str = f"{dur['hour']}h{dur.get('minute', 0):02d}m"
                elif dur.get("minute"):
                    dur_str = f"{dur['minute']}min"

                dist = seg.get("duration_distance", 0)
                dist_unit = seg.get("distance_unit_selected", "")
                dist_str = f"{dist}{dist_unit}" if dist else ""

                pct = seg.get("intensity_percent", {})
                pct_str = f"@{pct.get('min', 0)}-{pct.get('max', 0)}%CP" if pct.get("min") else ""

                part = f"{cls}: {dur_str or dist_str} {pct_str}".strip()
                if repeat > 1:
                    part = f"{repeat}x({part})"
                desc_parts.append(part)

        description = " | ".join(desc_parts) if desc_parts else title

        row = {
            "date": workout_date,
            "workout_type": workout_type,
            "planned_duration_min": str(duration_min) if duration_min else "",
            "planned_distance_km": str(distance_km) if distance_km else "",
            "target_power_min": power_min,
            "target_power_max": power_max,
            "workout_description": description,
        }
        print(f"    {workout_date} — {workout_type} ({duration_min}min, {distance_km}km)")
        rows.append(row)

    return rows


def _round_or_empty(val, decimals: int = 1) -> str:
    """Round a numeric value to N decimals, or return empty string if None."""
    if val is None:
        return ""
    return str(round(float(val), decimals))


# --- Sync entry point ---


def sync(
    data_dir: str,
    email: str | None = None,
    password: str | None = None,
    from_date: str | None = None,
) -> None:
    """Pull Stryd data and save to CSVs.

    Auth strategy: login via Stryd API with email/password to get a bearer token
    and user ID, then use both for API calls. If the token expires (401), re-login
    and retry.
    """
    if not email or not password:
        print("Stryd: skipped (STRYD_EMAIL / STRYD_PASSWORD not set)")
        return

    start = from_date or (date.today() - timedelta(days=7)).isoformat()
    print(f"Stryd: syncing from {start}")

    # Login to get bearer token and user ID
    try:
        user_id, token = _login_api(email, password)
    except Exception as e:
        print(f"  Stryd API login failed ({e})")
        return

    # Fetch activities
    activity_rows = []
    try:
        activity_rows = fetch_activities_api(user_id, token, from_date=start)
    except requests.HTTPError as e:
        status = e.response.status_code
        print(f"  Stryd API failed (HTTP {status})")
        # If 401, try re-login
        if status == 401:
            try:
                print("  Re-acquiring token...")
                user_id, token = _login_api(email, password)
                activity_rows = fetch_activities_api(user_id, token, from_date=start)
            except Exception as e2:
                print(f"  Re-login failed ({e2})")
    except Exception as e:
        print(f"  Stryd API failed ({e})")

    # Fetch training plan
    plan_rows = []
    try:
        # Get CP from the most recent activity for power target conversion
        cp_watts = None
        if activity_rows:
            for row in activity_rows:
                cp_val = row.get("cp_estimate", "")
                if cp_val:
                    cp_watts = float(cp_val)
                    break
        plan_rows = fetch_training_plan_api(user_id, token, cp_watts=cp_watts)
    except requests.HTTPError as e:
        status = e.response.status_code
        print(f"  Training plan API failed (HTTP {status})")
        if status == 401:
            try:
                print("  Re-acquiring token for training plan...")
                user_id, token = _login_api(email, password)
                plan_rows = fetch_training_plan_api(user_id, token, cp_watts=cp_watts)
            except Exception as e2:
                print(f"  Training plan re-login failed ({e2})")
    except Exception as e:
        print(f"  Training plan API failed ({e})")

    if activity_rows:
        power_path = os.path.join(data_dir, "stryd", "power_data.csv")
        append_rows(power_path, activity_rows, key_column="start_time")
        print(f"  Saved {len(activity_rows)} activities to power_data.csv")

    if plan_rows:
        plan_path = os.path.join(data_dir, "stryd", "training_plan.csv")
        append_rows(plan_path, plan_rows, key_column="date")
        print(f"  Saved {len(plan_rows)} planned workouts to training_plan.csv")


if __name__ == "__main__":
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    parser = argparse.ArgumentParser(description="Sync Stryd data")
    parser.add_argument("--from-date", help="Start date (YYYY-MM-DD) for historical backfill")
    args = parser.parse_args()

    email = os.environ.get("STRYD_EMAIL")
    password = os.environ.get("STRYD_PASSWORD")
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    sync(data_dir, email=email, password=password, from_date=args.from_date)
