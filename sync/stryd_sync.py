"""Stryd API integration — fetch/parse layer for the sync API route.

Provides login, activity fetch, training plan fetch, lap split computation,
and workout upload/delete via the Stryd calendar and activity APIs.
"""
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone

import requests

logger = logging.getLogger(__name__)


def _workout_type_from_name(name: str) -> str:
    """Extract workout type from Stryd plan name like 'Day 46 - Steady Aerobic'."""
    m = re.match(r"Day\s+\d+\s*-\s*(.+)", name)
    return m.group(1).strip().lower() if m else name.lower()


# --- API-based fetch ---

STRYD_LOGIN_URL = "https://www.stryd.com/b/email/signin"
STRYD_CALENDAR_API = "https://api.stryd.com/b/api/v1/users/{user_id}/calendar"
STRYD_ACTIVITY_API = "https://api.stryd.com/b/api/v1/activities/{activity_id}"
STRYD_WORKOUT_API = "https://api.stryd.com/b/api/v1/users/{user_id}/workouts"
STRYD_ESTIMATE_API = "https://api.stryd.com/b/api/v1/users/workouts/estimate"
STRYD_USER_API = "https://api.stryd.com/b/api/v1/users/{user_id}"


def _login_api(email: str, password: str) -> tuple[str, str]:
    """Login via Stryd API. Returns (user_id, token)."""
    logger.debug("  Logging in via Stryd API...")
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
    logger.debug(f"  Login successful (user_id={user_id})")
    return user_id, token


def fetch_current_cp(user_id: str, token: str) -> float | None:
    """Fetch the user's current Critical Power from their Stryd profile.

    The profile's training_info.critical_power is the rolling CP calculated
    by Stryd (typically over 90 days). This is the authoritative current value
    shown on Stryd's Power Center. Per-activity ftp is a snapshot at activity
    time and may lag behind the profile value.
    """
    url = STRYD_USER_API.format(user_id=user_id)
    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        training_info = data.get("training_info") or {}
        cp = training_info.get("critical_power")
        if cp is not None:
            cp = round(float(cp), 1)
            logger.debug(f"  Current CP from profile: {cp}W")
            return cp
        logger.debug("  No CP found in user profile training_info")
        return None
    except Exception as e:
        logger.debug(f"  Failed to fetch current CP: {e}")
        return None


def fetch_activity_splits(
    activity_id: str,
    token: str,
) -> list[dict]:
    """Fetch per-lap splits from a Stryd activity detail.

    Uses the activity's lap_events timestamps and per-second time series
    (total_power_list, heart_rate_list, speed_list, distance_list) to
    compute per-lap averages.

    Returns list of split dicts compatible with sync_writer.write_splits().
    """
    url = STRYD_ACTIVITY_API.format(activity_id=activity_id)
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    power_list = data.get("total_power_list", [])
    hr_list = data.get("heart_rate_list", [])
    speed_list = data.get("speed_list", [])
    distance_list = data.get("distance_list", [])
    ts_list = data.get("timestamp_list", [])
    lap_events = data.get("lap_events", [])
    start_events = data.get("start_events", [])
    stop_events = data.get("stop_events", [])

    if not ts_list or not power_list:
        return []

    # Build lap boundaries: [start, lap1, lap2, ..., end]
    start_ts = start_events[0] if start_events else ts_list[0]
    end_ts = stop_events[0] if stop_events else ts_list[-1]
    boundaries = [start_ts] + lap_events + [end_ts]

    splits = []
    for i in range(len(boundaries) - 1):
        lap_start = boundaries[i]
        lap_end = boundaries[i + 1]

        # Find index range in time series
        start_idx = None
        end_idx = None
        for j, t in enumerate(ts_list):
            if t >= lap_start and start_idx is None:
                start_idx = j
            if t >= lap_end:
                end_idx = j
                break
        if start_idx is None:
            continue
        if end_idx is None:
            end_idx = len(ts_list)
        if end_idx <= start_idx:
            continue

        lap_power = power_list[start_idx:end_idx]
        lap_hr = hr_list[start_idx:end_idx]
        lap_speed = speed_list[start_idx:end_idx]
        lap_dist = distance_list[start_idx:end_idx]

        n = len(lap_power)
        if n == 0:
            continue

        duration_sec = lap_end - lap_start
        avg_power = round(sum(lap_power) / n, 1)
        avg_hr = round(sum(lap_hr) / n) if lap_hr else None
        dist_m = (lap_dist[-1] - lap_dist[0]) if len(lap_dist) >= 2 else 0
        dist_km = round(dist_m / 1000, 3)
        avg_pace = round(duration_sec / dist_km, 1) if dist_km > 0.01 else None

        splits.append({
            "activity_id": str(activity_id),
            "split_num": i + 1,
            "distance_km": str(dist_km),
            "duration_sec": str(duration_sec),
            "avg_power": str(avg_power),
            "avg_hr": str(avg_hr) if avg_hr else "",
            "avg_pace_min_km": str(avg_pace) if avg_pace else "",
        })

    return splits


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
    logger.debug(f"  API returned {len(activities)} activities")

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
            "activity_id": str(act.get("id", "")),
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
        logger.debug(f"    {row['date']} — {row['avg_power']}W, {row['distance_km']}km, RSS={row['rss']}")
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

    workouts = data.get("workouts") or []
    logger.debug(f"  Plan API returned {len(workouts)} planned workouts")

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
        logger.debug(f"    {workout_date} — {workout_type} ({duration_min}min, {distance_km}km)")
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


def _round_or_empty(val: float | int | None, decimals: int = 1) -> str:
    """Round a numeric value to N decimals, or return empty string if None."""
    if val is None:
        return ""
    return str(round(float(val), decimals))


# --- Workout upload ---

# Map AI plan workout_type to Stryd workout type strings
_STRYD_WORKOUT_TYPES: dict[str, str] = {
    "easy": "easy run",
    "recovery": "recovery",
    "long_run": "long run",
    "long run": "long run",
    "steady_aerobic": "steady state",
    "tempo": "tempo",
    "threshold": "threshold",
    "interval": "intervals",
    "repetition": "repetition",
    "hill_repeat": "hill repeat",
}


def _make_segment(
    intensity_class: str,
    minutes: float,
    cp_min_pct: int,
    cp_max_pct: int,
) -> dict:
    """Build a single Stryd workout segment."""
    h = int(minutes // 60)
    m = int(minutes % 60)
    s = int((minutes * 60) % 60)
    return {
        "desc": "",
        "desc_no_cp": "",
        "duration_type": "time",
        "duration_time": {"hour": h, "minute": m, "second": s},
        "intensity_class": intensity_class,
        "intensity_type": "percentage",
        "intensity_percent": {
            "min": cp_min_pct,
            "max": cp_max_pct,
            "value": (cp_min_pct + cp_max_pct) // 2,
        },
        "flexible": False,
        "incline": 0,
        "grade": 0,
        "distance_unit_selected": "km",
        "duration_distance": 0,
        "pdc_target": 0,
        "rpe_selected": 1,
        "zone_selected": 0,
        "uuid": str(uuid.uuid4()),
    }


def _parse_structured_description(
    description: str, cp_watts: float
) -> list[dict] | None:
    """Parse AI plan descriptions like 'WU 15min, 3x3min @275-290W w/ 3min jog recovery, CD 10min'.

    Returns list of Stryd blocks if parseable, None if description is unstructured.
    """
    if not description:
        return None

    # Strip trailing markers like [DONE]
    desc = re.sub(r"\s*\[DONE\]\s*$", "", description).strip()

    blocks: list[dict] = []

    # Try to extract structured segments from comma-separated parts
    # Pattern: "WU 15min, 3x3min @275-290W w/ 3min jog recovery, CD 10min"
    parts = [p.strip() for p in desc.split(",")]

    for part in parts:
        part_lower = part.lower()

        # Warmup: "WU 15min" or "WU 10min easy"
        wu_match = re.match(r"wu\s+(\d+)\s*min", part_lower)
        if wu_match:
            mins = int(wu_match.group(1))
            blocks.append({
                "uuid": str(uuid.uuid4()),
                "repeat": 1,
                "segments": [_make_segment("warmup", mins, 65, 75)],
            })
            continue

        # Cooldown: "CD 10min"
        cd_match = re.match(r"cd\s+(\d+)\s*min", part_lower)
        if cd_match:
            mins = int(cd_match.group(1))
            blocks.append({
                "uuid": str(uuid.uuid4()),
                "repeat": 1,
                "segments": [_make_segment("cooldown", mins, 65, 75)],
            })
            continue

        # Intervals: "3x3min @275-290W w/ 3min jog recovery"
        # or "4x4min @265-280W w/ 3min jog recovery"
        interval_match = re.match(
            r"(\d+)x(\d+)\s*min\s+@(\d+)-(\d+)w\s+w/\s+(\d+)\s*min",
            part_lower,
        )
        if interval_match:
            reps = int(interval_match.group(1))
            work_min = int(interval_match.group(2))
            power_min = int(interval_match.group(3))
            power_max = int(interval_match.group(4))
            rest_min = int(interval_match.group(5))
            work_cp_min = round(power_min / cp_watts * 100)
            work_cp_max = round(power_max / cp_watts * 100)
            blocks.append({
                "uuid": str(uuid.uuid4()),
                "repeat": reps,
                "segments": [
                    _make_segment("work", work_min, work_cp_min, work_cp_max),
                    _make_segment("rest", rest_min, 55, 65),
                ],
            })
            continue

        # Tempo block: "15min @220-240W"
        tempo_match = re.match(r"(\d+)\s*min\s+@(\d+)-(\d+)w", part_lower)
        if tempo_match:
            mins = int(tempo_match.group(1))
            power_min = int(tempo_match.group(2))
            power_max = int(tempo_match.group(3))
            cp_min = round(power_min / cp_watts * 100)
            cp_max = round(power_max / cp_watts * 100)
            blocks.append({
                "uuid": str(uuid.uuid4()),
                "repeat": 1,
                "segments": [_make_segment("work", mins, cp_min, cp_max)],
            })
            continue

    # Only return if we parsed at least a warmup or work block
    has_content = any(
        seg.get("intensity_class") in ("warmup", "work")
        for b in blocks
        for seg in b.get("segments", [])
    )
    return blocks if has_content else None


def build_workout_blocks(workout: dict, cp_watts: float) -> list[dict]:
    """Convert an AI plan workout dict to Stryd API block format.

    Args:
        workout: Dict with keys from the AI plan CSV (workout_type, planned_duration_min,
                 target_power_min, target_power_max, workout_description).
        cp_watts: Current Critical Power in watts for percentage conversion.

    Returns:
        List of Stryd block dicts ready for the create workout API.
    """
    description = workout.get("workout_description", "")

    # Try parsing structured descriptions first (interval/threshold/tempo workouts)
    parsed = _parse_structured_description(description, cp_watts)
    if parsed:
        return parsed

    # Fallback: build a simple single-block workout from power targets and duration
    duration_min = float(workout.get("planned_duration_min") or 0)
    power_min = workout.get("target_power_min")
    power_max = workout.get("target_power_max")
    workout_type = (workout.get("workout_type") or "easy").lower()

    if power_min and power_max and cp_watts:
        cp_min_pct = round(float(power_min) / cp_watts * 100)
        cp_max_pct = round(float(power_max) / cp_watts * 100)
    else:
        # Default zones by workout type
        defaults = {
            "easy": (65, 75),
            "recovery": (55, 65),
            "long_run": (68, 78),
            "long run": (68, 78),
            "steady_aerobic": (72, 82),
            "tempo": (82, 92),
            "threshold": (88, 100),
            "interval": (100, 110),
        }
        cp_min_pct, cp_max_pct = defaults.get(workout_type, (65, 75))

    # Determine intensity class
    if workout_type in ("easy", "recovery"):
        intensity = "warmup"  # Stryd uses warmup for easy/recovery single-block
    elif workout_type in ("tempo", "threshold", "interval", "steady_aerobic"):
        intensity = "work"
    else:
        intensity = "warmup"

    if duration_min <= 0:
        duration_min = 30  # default

    return [{
        "uuid": str(uuid.uuid4()),
        "repeat": 1,
        "segments": [_make_segment(intensity, duration_min, cp_min_pct, cp_max_pct)],
    }]


def create_workout_api(
    user_id: str,
    token: str,
    workout_date: str,
    title: str,
    blocks: list[dict],
    workout_type: str = "",
    description: str = "",
    surface: str = "road",
) -> dict:
    """Create a structured workout on the Stryd calendar.

    Args:
        workout_date: ISO date string like '2026-04-10'.
        title: Workout name shown in the calendar.
        blocks: List of Stryd block dicts (from build_workout_blocks).
        workout_type: Stryd workout type string (e.g., 'easy run', 'intervals').
        description: Free-text description.
        surface: 'road', 'track', 'trail', or 'treadmill'.

    Returns:
        The created workout response dict (includes server-assigned id, stress, etc).
    """
    # Convert date to Unix timestamp at midnight UTC
    dt = datetime.strptime(workout_date, "%Y-%m-%d")
    timestamp = int(dt.replace(tzinfo=timezone.utc).timestamp())

    url = STRYD_WORKOUT_API.format(user_id=user_id)
    payload = {
        "type": workout_type,
        "desc": description,
        "title": title,
        "blocks": blocks,
        "id": -1,
        "objective": "",
        "source": "USER",
        "duration": 0,
        "stress": 0,
        "surface": surface,
        "tags": None,
    }

    resp = requests.post(
        url,
        params={"timestamp": timestamp},
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def delete_workout_api(user_id: str, token: str, workout_id: str) -> bool:
    """Delete a workout from the Stryd calendar.

    Returns True if successfully deleted.
    """
    url = f"{STRYD_WORKOUT_API.format(user_id=user_id)}/{workout_id}"
    resp = requests.delete(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return True
