"""intervals.icu sync — HTTP layer and canonical row parsers.

intervals.icu uses HTTP Basic Auth. Per V1 verification (2026-04-22),
username is the literal string "API_KEY" and password is the user's PAT.
The athlete_id is used only for URL path segments, not auth.

Endpoints:
- GET  /api/v1/athlete/{id}                         — profile (sportSettings)
- GET  /api/v1/athlete/{id}/activities              — activity list (date-windowed)
- GET  /api/v1/activity/{id}?intervals=true         — activity detail + icu_intervals
- GET  /api/v1/athlete/{id}/wellness                — wellness rows (date-windowed)
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Any

import requests

logger = logging.getLogger(__name__)

INTERVALS_BASE_URL = "https://intervals.icu/api/v1"
DEFAULT_TIMEOUT_SEC = 15
MAX_RETRIES = 4
INITIAL_BACKOFF_SEC = 1.0
USER_AGENT = "praxys/intervals-icu-sync"


def _build_auth(credentials: dict) -> tuple[str, str]:
    """Return the (username, password) tuple for HTTP Basic Auth.

    intervals.icu requires username=literal 'API_KEY', password=<PAT>.
    """
    return ("API_KEY", credentials["api_key"])


class IntervalsIcuError(Exception):
    """Base exception for intervals.icu sync errors."""


class IntervalsIcuUnauthorized(IntervalsIcuError):
    """401 — credentials invalid or revoked. Caller should mark status='expired'."""


class IntervalsIcuRateLimited(IntervalsIcuError):
    """429 — rate limited after MAX_RETRIES backoff attempts."""


class IntervalsIcuServerError(IntervalsIcuError):
    """5xx after retries."""


def _request(
    path: str,
    *,
    credentials: dict,
    params: dict[str, Any] | None = None,
) -> Any:
    """GET a JSON endpoint with Basic auth, 15s timeout, and retry.

    Retry policy:
    - 401 -> raise IntervalsIcuUnauthorized (no retry)
    - 429 -> exponential backoff 1s -> 2s -> 4s -> 8s, MAX_RETRIES attempts total
    - 5xx -> same backoff, same retry budget
    - Network timeout -> treat as 5xx
    """
    url = f"{INTERVALS_BASE_URL}{path}"
    auth = _build_auth(credentials)
    headers = {"User-Agent": USER_AGENT}
    backoff = INITIAL_BACKOFF_SEC
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(
                url,
                params=params,
                auth=auth,
                headers=headers,
                timeout=DEFAULT_TIMEOUT_SEC,
            )
        except requests.Timeout as exc:
            last_error = exc
            logger.warning("intervals.icu timeout on %s attempt=%d", path, attempt + 1)
            if attempt < MAX_RETRIES - 1:
                time.sleep(backoff)
                backoff *= 2
            continue

        if resp.status_code == 401:
            raise IntervalsIcuUnauthorized(f"401 from {path}")

        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = requests.HTTPError(f"{resp.status_code} from {path}")
            logger.warning(
                "intervals.icu %d on %s attempt=%d; backoff=%.1fs",
                resp.status_code, path, attempt + 1, backoff,
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(backoff)
                backoff *= 2
            continue

        resp.raise_for_status()
        return resp.json()

    if isinstance(last_error, requests.HTTPError) and "429" in str(last_error):
        raise IntervalsIcuRateLimited(str(last_error))
    raise IntervalsIcuServerError(str(last_error) if last_error else "unknown")


# Normalize intervals.icu sport types to Praxys canonical types.
# V4 verified (2026-04-22): athlete i302653 returned Run, VirtualRun, TrailRun,
# Ride, VirtualRide, VirtualRow, Hike, Walk. Include additional common types.
_SPORT_TYPE_MAP = {
    "run": "running",
    "virtualrun": "running",
    "trailrun": "trail_running",
    "walk": "walking",
    "hike": "hiking",
    "ride": "cycling",
    "virtualride": "cycling",
    "ebikeride": "cycling",
    "virtualrow": "rowing",
    "row": "rowing",
    "swim": "swimming",
    "openwaterswim": "swimming",
    "workout": "strength",
    "weighttraining": "strength",
}


def _round_or_empty(val: Any, decimals: int = 1) -> str:
    """Round numeric -> str, or return empty string for missing values."""
    if val is None or val == "":
        return ""
    try:
        return str(round(float(val), decimals))
    except (TypeError, ValueError):
        return ""


def _map_activity_type(raw_type: str) -> str:
    key = str(raw_type).replace(" ", "").replace("_", "").lower()
    return _SPORT_TYPE_MAP.get(key, "other")


def _parse_activity(activity: dict) -> dict:
    """Convert one intervals.icu activity summary to Praxys canonical row shape.

    Key transformations:
    - id prefixed with 'icu_' to avoid cross-source ID collision
    - distance m -> km
    - cadence single-leg -> double-leg (x 2) for running
    - icu_average_watts preferred over average_watts (Stryd-style running power)
    - training_load, training_effect intentionally left null — Praxys recomputes
    """
    raw_id = str(activity.get("id") or "")
    start_local = str(activity.get("start_date_local") or "")
    sport_type = str(activity.get("type") or "")
    activity_type = _map_activity_type(sport_type)

    distance_m = float(activity.get("distance") or 0)
    moving_time = float(activity.get("moving_time") or 0)
    distance_km = round(distance_m / 1000, 3) if distance_m > 0 else 0.0
    avg_pace_sec_km = (
        round(moving_time / distance_km, 1)
        if distance_km > 0 and moving_time > 0
        else None
    )

    avg_power = activity.get("icu_average_watts")
    if avg_power in (None, ""):
        avg_power = activity.get("average_watts")

    raw_cadence = activity.get("average_cadence")
    avg_cadence_spm = (
        float(raw_cadence) * 2 if raw_cadence not in (None, "") and activity_type == "running"
        else raw_cadence
    )

    return {
        "activity_id": f"icu_{raw_id}",
        "date": start_local[:10],
        "start_time": start_local,
        "activity_type": activity_type,
        "distance_km": str(distance_km) if distance_km > 0 else "",
        "duration_sec": str(moving_time) if moving_time > 0 else "",
        "avg_power": _round_or_empty(avg_power),
        "max_power": _round_or_empty(activity.get("max_watts")),
        "avg_hr": _round_or_empty(activity.get("average_heartrate")),
        "max_hr": _round_or_empty(activity.get("max_heartrate")),
        "avg_pace_sec_km": _round_or_empty(avg_pace_sec_km),
        "elevation_gain_m": _round_or_empty(activity.get("total_elevation_gain")),
        "avg_cadence": _round_or_empty(avg_cadence_spm),
        "source": "intervals_icu",
    }


def _parse_laps(
    prefixed_activity_id: str,
    activity_detail: dict,
    *,
    activity_type: str,
) -> list[dict]:
    """Convert intervals.icu `icu_intervals` field to Praxys canonical split rows.

    Per V3 verification (2026-04-22): intervals.icu exposes post-processed
    intervals (WORK / RECOVERY / etc.) via the `icu_intervals` field when the
    activity detail is fetched with `?intervals=true`. These are NOT raw
    device laps. Per-interval elevation is not exposed, so
    `elevation_change_m` stays empty.

    Preserves array order (do not re-segment).
    """
    rows: list[dict] = []
    for idx, lap in enumerate(activity_detail.get("icu_intervals") or [], start=1):
        distance_m = float(lap.get("distance") or 0)
        moving_time = float(lap.get("moving_time") or 0)
        distance_km = round(distance_m / 1000, 3) if distance_m > 0 else 0.0
        avg_pace_sec_km = (
            round(moving_time / distance_km, 1)
            if distance_km > 0 and moving_time > 0
            else None
        )
        raw_cadence = lap.get("average_cadence")
        avg_cadence_spm = (
            float(raw_cadence) * 2 if raw_cadence not in (None, "") and activity_type == "running"
            else raw_cadence
        )

        rows.append({
            "activity_id": prefixed_activity_id,
            "split_num": str(idx),
            "distance_km": str(distance_km) if distance_km > 0 else "",
            "duration_sec": str(moving_time) if moving_time > 0 else "",
            "avg_power": _round_or_empty(lap.get("average_watts")),
            "avg_hr": _round_or_empty(lap.get("average_heartrate")),
            "max_hr": _round_or_empty(lap.get("max_heartrate")),
            "avg_cadence": _round_or_empty(avg_cadence_spm),
            "avg_pace_sec_km": _round_or_empty(avg_pace_sec_km),
            "elevation_change_m": "",
        })
    return rows
