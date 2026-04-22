"""intervals.icu sync — HTTP layer and canonical row parsers.

intervals.icu uses HTTP Basic Auth. Per V1 verification (2026-04-22),
username is the literal string "API_KEY" and password is the user's PAT.
The athlete_id is used only for URL path segments, not auth.

Endpoints:
- GET  /api/v1/athlete/{id}                         — profile (sportSettings)
- GET  /api/v1/athlete/{id}/activities              — activity list (date-windowed)
- GET  /api/v1/activity/{id}?intervals=true         — activity detail + icu_intervals
- GET  /api/v1/athlete/{id}/wellness                — wellness rows (date-windowed)

Retry policy (exception hierarchy):
- IntervalsIcuUnauthorized  — 401, no retry
- IntervalsIcuClientError   — 4xx other than 401/429, no retry
- IntervalsIcuRateLimited   — 429 after MAX_RETRIES backoff attempts
- IntervalsIcuServerError   — 5xx after MAX_RETRIES backoff attempts
- Network timeout treated as 5xx for retry purposes
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


class IntervalsIcuClientError(IntervalsIcuError):
    """Non-retryable client error: 4xx other than 401/429."""


def _request(
    path: str,
    *,
    credentials: dict,
    params: dict[str, Any] | None = None,
) -> Any:
    """GET a JSON endpoint with Basic auth, 15s timeout, and retry.

    Retry policy:
    - 401 -> raise IntervalsIcuUnauthorized (no retry)
    - 4xx other than 401/429 -> raise IntervalsIcuClientError (no retry)
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

        if 400 <= resp.status_code < 500:
            # 401 and 429 are handled above; anything else 4xx is a hard error.
            raise IntervalsIcuClientError(
                f"{resp.status_code} from {path}: {resp.text[:200]}"
            )

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


def _parse_wellness(wellness_rows: list[dict]) -> list[dict]:
    """Convert intervals.icu wellness rows to Praxys recovery_data rows."""
    rows: list[dict] = []
    for w in wellness_rows:
        rows.append({
            "date": str(w.get("id") or "")[:10],
            "readiness_score": _round_or_empty(w.get("readiness")),
            "hrv_avg": _round_or_empty(w.get("hrv"), decimals=2),
            "resting_hr": _round_or_empty(w.get("restingHR")),
            "sleep_score": _round_or_empty(w.get("sleepScore")),
            "total_sleep_sec": _round_or_empty(w.get("sleepSecs"), decimals=0),
            "deep_sleep_sec": "",
            "rem_sleep_sec": "",
            "body_temp_delta": "",
            "source": "intervals_icu",
        })
    return rows


def _parse_thresholds(profile: dict, today: date) -> list[dict]:
    """Extract running thresholds from athlete profile sportSettings.

    V2 verified (2026-04-22): intervals.icu sportSettings for a Run-typed
    entry exposes `ftp`, `lthr`, `max_hr`, `threshold_pace`. The
    `threshold_pace` value is in meters per second — Praxys stores pace
    as seconds per km, so convert: sec_per_km = 1000 / m_per_s.

    Maps to Praxys fitness_data metric_type values:
      ftp            -> cp_estimate
      lthr           -> lthr_bpm
      threshold_pace -> lt_pace_sec_km  (unit-converted)
      max_hr         -> max_hr_bpm
    """
    rows: list[dict] = []
    today_str = today.strftime("%Y-%m-%d")
    for setting in profile.get("sportSettings") or []:
        types = setting.get("types") or []
        if "Run" not in types and "TrailRun" not in types:
            continue

        pace_mps = setting.get("threshold_pace")
        pace_sec_km = (
            round(1000 / float(pace_mps), 2)
            if pace_mps not in (None, "", 0, 0.0)
            else None
        )

        metric_map = {
            "cp_estimate": setting.get("ftp"),
            "lthr_bpm": setting.get("lthr"),
            "lt_pace_sec_km": pace_sec_km,
            "max_hr_bpm": setting.get("max_hr"),
        }
        for metric_type, value in metric_map.items():
            if value in (None, ""):
                continue
            rows.append({
                "date": today_str,
                "metric_type": metric_type,
                "value": _round_or_empty(value, decimals=2),
                "source": "intervals_icu",
            })
        break  # first Run-containing entry wins
    return rows


def fetch_athlete_profile_api(credentials: dict) -> dict:
    """GET /athlete/{id}. Returns the profile payload."""
    athlete_id = credentials["athlete_id"]
    return _request(f"/athlete/{athlete_id}", credentials=credentials)


def fetch_activities_api(
    credentials: dict,
    from_date: str,
    to_date: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """GET /athlete/{id}/activities?oldest&newest.

    Returns (canonical_rows, raw_activity_dicts). Raw is kept so the caller
    can use it to decide which activity details to fetch for laps.
    """
    athlete_id = credentials["athlete_id"]
    if to_date is None:
        to_date = datetime.utcnow().date().isoformat()
    params = {"oldest": from_date, "newest": to_date}
    raw_activities = _request(
        f"/athlete/{athlete_id}/activities",
        credentials=credentials,
        params=params,
    ) or []
    parsed = [_parse_activity(a) for a in raw_activities]
    return parsed, raw_activities


def fetch_activity_laps(
    activity_id: str,
    credentials: dict,
    *,
    activity_type: str,
) -> list[dict]:
    """GET /activity/{id}?intervals=true. Returns Praxys canonical split rows.

    V3 verified (2026-04-22): the param is `intervals=true` (not
    `include_laps=true`); per-interval data is in the response's
    `icu_intervals` field. These are post-processed intervals
    (WORK/RECOVERY/etc.), not raw device laps.

    `activity_id` is the raw intervals.icu id (no 'icu_' prefix). The prefix
    is added by _parse_laps().
    """
    detail = _request(
        f"/activity/{activity_id}",
        credentials=credentials,
        params={"intervals": "true"},
    )
    return _parse_laps(f"icu_{activity_id}", detail, activity_type=activity_type)


def fetch_wellness_api(
    credentials: dict,
    from_date: str,
    to_date: str | None = None,
) -> list[dict]:
    """GET /athlete/{id}/wellness?oldest&newest. Returns canonical recovery rows."""
    athlete_id = credentials["athlete_id"]
    if to_date is None:
        to_date = datetime.utcnow().date().isoformat()
    params = {"oldest": from_date, "newest": to_date}
    raw = _request(
        f"/athlete/{athlete_id}/wellness",
        credentials=credentials,
        params=params,
    ) or []
    return _parse_wellness(raw)


from dataclasses import dataclass
from datetime import date as _date


@dataclass
class SyncResult:
    activities_written: int = 0
    splits_written: int = 0
    wellness_written: int = 0
    thresholds_written: int = 0


def sync_all(
    *,
    user_id: str,
    credentials: dict,
    db,
    since: _date,
    today: _date | None = None,
) -> SyncResult:
    """Orchestrate all intervals.icu sync work for one user.

    Fetches activities in the date window, then per-activity intervals,
    then wellness, then athlete profile thresholds. Writes everything
    through db.sync_writer helpers. Returns per-table counts.
    """
    from db.sync_writer import (
        write_activities,
        write_fitness,
        write_recovery_rows,
        write_splits_replace,
    )

    today = today or _date.today()
    from_str = since.isoformat()
    to_str = today.isoformat()

    result = SyncResult()

    activity_rows, raw_activities = fetch_activities_api(credentials, from_str, to_str)
    result.activities_written = write_activities(user_id, activity_rows, db)

    all_split_rows: list[dict] = []
    for raw in raw_activities:
        raw_id = str(raw.get("id") or "")
        if not raw_id:
            continue
        activity_type = _map_activity_type(str(raw.get("type") or ""))
        try:
            split_rows = fetch_activity_laps(raw_id, credentials, activity_type=activity_type)
        except IntervalsIcuError as exc:
            logger.warning("intervals.icu laps fetch failed for %s: %s", raw_id, exc)
            continue
        all_split_rows.extend(split_rows)
    result.splits_written = write_splits_replace(user_id, all_split_rows, db)

    wellness_rows = fetch_wellness_api(credentials, from_str, to_str)
    result.wellness_written = write_recovery_rows(user_id, wellness_rows, "intervals_icu", db)

    profile = fetch_athlete_profile_api(credentials)
    threshold_rows = _parse_thresholds(profile, today)
    result.thresholds_written = write_fitness(user_id, threshold_rows, "intervals_icu", db)

    return result
