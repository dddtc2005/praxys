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
STRYD_ACTIVITY_API = "https://api.stryd.com/b/api/v1/activities/{activity_id}"


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
) -> tuple[list[dict], list[dict]]:
    """Fetch completed activities from the Stryd calendar API.

    Args:
        user_id: Stryd user UUID.
        token: Bearer token for Stryd API.
        from_date: Start date (YYYY-MM-DD).
        to_date: End date (YYYY-MM-DD), defaults to today.

    Returns:
        Tuple of (parsed CSV rows, raw API activity objects).
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
    raw_activities = []  # Keep raw API objects for detail fetching
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
        raw_activities.append(act)  # Keep raw for detail fetch

    return rows, raw_activities


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


def fetch_activity_detail_api(
    activity_id: int,
    token: str,
) -> dict:
    """Fetch per-second time-series data for a single Stryd activity.

    Returns the full activity object with populated *_list fields.
    Raises requests.HTTPError on API failure.
    """
    url = STRYD_ACTIVITY_API.format(activity_id=activity_id)
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def compute_lap_splits(activity: dict, activity_id: str) -> list[dict]:
    """Compute per-lap averages from time-series data + lap timestamps.

    Uses lap_timestamp_list to define lap boundaries, then slices per-second
    arrays to compute averages for each lap.

    Returns list of dicts matching the activity_splits.csv schema.
    """
    timestamps = activity.get("timestamp_list") or []
    lap_timestamps = activity.get("lap_timestamp_list") or []
    power_data = activity.get("total_power_list") or []
    hr_data = activity.get("heart_rate_list") or []
    cadence_data = activity.get("cadence_list") or []
    speed_data = activity.get("speed_list") or []
    distance_data = activity.get("distance_list") or []
    elevation_data = activity.get("elevation_list") or []
    ground_time_data = activity.get("ground_time_list") or []
    oscillation_data = activity.get("oscillation_list") or []
    leg_spring_data = activity.get("leg_spring_list") or []

    if not timestamps or not lap_timestamps:
        return []

    # Build lap boundaries: start_time -> [lap1_end, lap2_end, ...]
    # Laps come in pairs for auto-laps or as single events
    start_ts = timestamps[0]

    # Build index lookup: timestamp -> array index
    ts_to_idx: dict[int, int] = {}
    for i, ts in enumerate(timestamps):
        ts_to_idx[ts] = i

    def _find_idx(ts: int) -> int:
        """Find closest index for a timestamp."""
        if ts in ts_to_idx:
            return ts_to_idx[ts]
        # Find nearest
        closest = min(timestamps, key=lambda t: abs(t - ts))
        return ts_to_idx[closest]

    # Build lap segments from boundaries: [start, lap1, lap2, ..., end]
    end_ts = timestamps[-1]
    boundaries = sorted(set([start_ts] + lap_timestamps + [end_ts]))
    # Filter out boundaries that are too close together (< 10 seconds = noise)
    filtered = [boundaries[0]]
    for b in boundaries[1:]:
        if b - filtered[-1] >= 10:
            filtered.append(b)
    boundaries = filtered

    def _safe_avg(data: list, start_idx: int, end_idx: int) -> float | None:
        """Average of a slice, skipping None values. Returns None if no valid data."""
        if not data or start_idx >= len(data):
            return None
        segment = data[start_idx:min(end_idx, len(data))]
        valid = [v for v in segment if v is not None]
        return sum(valid) / len(valid) if valid else None

    rows: list[dict] = []
    for i in range(len(boundaries) - 1):
        lap_start = boundaries[i]
        lap_end = boundaries[i + 1]

        start_idx = _find_idx(lap_start)
        end_idx = _find_idx(lap_end)
        if end_idx <= start_idx:
            continue

        duration_sec = lap_end - lap_start

        # Distance from cumulative distance_list
        dist_start = distance_data[start_idx] if start_idx < len(distance_data) else 0
        dist_end = distance_data[min(end_idx, len(distance_data) - 1)] if distance_data else 0
        distance_m = (dist_end or 0) - (dist_start or 0)
        distance_km = round(distance_m / 1000, 3) if distance_m > 0 else 0

        # Elevation change
        elev_start = elevation_data[start_idx] if start_idx < len(elevation_data) else 0
        elev_end = elevation_data[min(end_idx, len(elevation_data) - 1)] if elevation_data else 0
        elev_change = round((elev_end or 0) - (elev_start or 0), 1)

        avg_power = _safe_avg(power_data, start_idx, end_idx)
        avg_hr = _safe_avg(hr_data, start_idx, end_idx)
        avg_cadence = _safe_avg(cadence_data, start_idx, end_idx)
        avg_speed = _safe_avg(speed_data, start_idx, end_idx)
        avg_gt = _safe_avg(ground_time_data, start_idx, end_idx)
        avg_osc = _safe_avg(oscillation_data, start_idx, end_idx)
        avg_ls = _safe_avg(leg_spring_data, start_idx, end_idx)

        # Derive pace from speed (sec/km)
        avg_pace = round(1000 / avg_speed, 1) if avg_speed and avg_speed > 0 else None

        rows.append({
            "activity_id": activity_id,
            "split_num": str(i + 1),
            "distance_km": str(distance_km),
            "duration_sec": str(duration_sec),
            "avg_power": _round_or_empty(avg_power),
            "avg_hr": _round_or_empty(avg_hr),
            "avg_cadence": _round_or_empty(avg_cadence),
            "avg_pace_sec_km": _round_or_empty(avg_pace),
            "avg_speed_ms": _round_or_empty(avg_speed, 3),
            "avg_ground_time_ms": _round_or_empty(avg_gt),
            "avg_oscillation": _round_or_empty(avg_osc),
            "avg_leg_spring": _round_or_empty(avg_ls),
            "elevation_change_m": str(elev_change),
        })

    return rows


def _get_existing_split_activity_ids(data_dir: str) -> set[str]:
    """Get set of activity IDs already in Stryd activity_splits.csv."""
    from sync.csv_utils import read_csv
    splits_path = os.path.join(data_dir, "stryd", "activity_splits.csv")
    existing = read_csv(splits_path)
    return {row["activity_id"] for row in existing if row.get("activity_id")}


def _fetch_stryd_splits(
    activity_rows: list[dict],
    token: str,
    email: str,
    password: str,
    data_dir: str,
) -> list[dict]:
    """Fetch per-lap splits for activities not already in splits CSV.

    Rate limits at 1 second between API calls. Handles 429 with exponential
    backoff and 401 with re-login.
    """
    import time

    existing_ids = _get_existing_split_activity_ids(data_dir)

    # activity_rows are raw calendar API objects with 'id' field for detail API
    all_splits: list[dict] = []
    new_activities = [a for a in activity_rows if str(a.get("id", "")) not in existing_ids]

    if not new_activities:
        return []

    print(f"  Fetching per-lap detail for {len(new_activities)} new activities...")
    current_token = token

    for i, act in enumerate(new_activities):
        act_id = act.get("id")
        if not act_id:
            continue

        act_id_str = str(act_id)
        if act_id_str in existing_ids:
            continue

        # Rate limit: 1 second between calls
        if i > 0:
            time.sleep(1)

        print(f"    [{i + 1}/{len(new_activities)}] Fetching detail for activity {act_id}...")

        retries = 0
        max_retries = 3
        backoff = 2

        while retries <= max_retries:
            try:
                detail = fetch_activity_detail_api(act_id, current_token)
                if detail:
                    splits = compute_lap_splits(detail, act_id_str)
                    if splits:
                        all_splits.extend(splits)
                        print(f"      {len(splits)} laps extracted")
                    else:
                        print(f"      No lap data available")
                break  # Success or no data — move to next activity

            except requests.HTTPError as e:
                status = e.response.status_code
                if status == 401:
                    # Re-login and retry
                    print(f"      Token expired, re-logging in...")
                    try:
                        _, current_token = _login_api(email, password)
                        retries += 1
                        continue
                    except Exception as e2:
                        print(f"      Re-login failed ({e2}), skipping remaining")
                        return all_splits
                elif status == 429:
                    # Rate limited — exponential backoff
                    wait = backoff ** (retries + 1)
                    print(f"      Rate limited (429), waiting {wait}s...")
                    time.sleep(wait)
                    retries += 1
                    if retries > max_retries:
                        print(f"      Max retries reached, saving {len(all_splits)} splits so far")
                        return all_splits
                    continue
                else:
                    print(f"      HTTP {status} for activity {act_id}, skipping")
                    break

            except requests.RequestException as e:
                print(f"      Network error for activity {act_id}: {e}, skipping")
                break

            except Exception as e:
                import traceback as tb
                print(f"      Error processing activity {act_id}: {e}")
                tb.print_exc()
                break

    return all_splits


def _round_or_empty(val: float | int | None, decimals: int = 1) -> str:
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
    raw_activities = []
    try:
        activity_rows, raw_activities = fetch_activities_api(user_id, token, from_date=start)
    except requests.HTTPError as e:
        status = e.response.status_code
        print(f"  Stryd API failed (HTTP {status})")
        # If 401, try re-login
        if status == 401:
            try:
                print("  Re-acquiring token...")
                user_id, token = _login_api(email, password)
                activity_rows, raw_activities = fetch_activities_api(user_id, token, from_date=start)
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

    # Fetch per-lap splits for new activities via activity detail API
    if raw_activities:
        split_rows = _fetch_stryd_splits(
            raw_activities, token, email, password, data_dir,
        )
        if split_rows:
            splits_path = os.path.join(data_dir, "stryd", "activity_splits.csv")
            append_rows(splits_path, split_rows, key_column=["activity_id", "split_num"])
            print(f"  Saved {len(split_rows)} splits to activity_splits.csv")


if __name__ == "__main__":
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    parser = argparse.ArgumentParser(description="Sync Stryd data")
    parser.add_argument("--from-date", help="Start date (YYYY-MM-DD) for historical backfill")
    args = parser.parse_args()

    email = os.environ.get("STRYD_EMAIL")
    password = os.environ.get("STRYD_PASSWORD")
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    sync(data_dir, email=email, password=password, from_date=args.from_date)
