"""Strava API integration helpers for OAuth, activity sync, and lap parsing."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_ATHLETE_API = "https://www.strava.com/api/v3/athlete"
STRAVA_ACTIVITIES_API = "https://www.strava.com/api/v3/athlete/activities"
STRAVA_ACTIVITY_LAPS_API = "https://www.strava.com/api/v3/activities/{activity_id}/laps"

DEFAULT_SCOPE = "read,activity:read_all,profile:read_all"

_SPORT_TYPE_MAP = {
    "run": "running",
    "trailrun": "trail_running",
    "walk": "walking",
    "hike": "hiking",
    "ride": "cycling",
    "ebikeride": "cycling",
    "virtualride": "cycling",
    "swim": "swimming",
    "workout": "strength",
    "weighttraining": "strength",
}


def build_authorize_url(
    client_id: str,
    redirect_uri: str,
    state: str,
    *,
    scope: str = DEFAULT_SCOPE,
    approval_prompt: str = "auto",
) -> str:
    """Build the Strava OAuth authorize URL."""

    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "approval_prompt": approval_prompt,
            "scope": scope,
            "state": state,
        }
    )
    return f"{STRAVA_AUTHORIZE_URL}?{query}"


def exchange_code_for_token(
    code: str,
    client_id: str,
    client_secret: str,
) -> dict:
    """Exchange an OAuth authorization code for Strava access credentials."""

    resp = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def refresh_access_token_if_needed(
    credentials: dict,
    client_id: str,
    client_secret: str,
    *,
    now: datetime | None = None,
) -> tuple[dict, bool]:
    """Refresh Strava OAuth credentials when expired or close to expiry.

    Returns ``(updated_credentials, changed)``. Strava rotates refresh tokens,
    so callers should persist the returned credentials whenever ``changed`` is
    true.
    """

    now = now or datetime.now(timezone.utc)
    expires_at = int(credentials.get("expires_at") or 0)
    # Refresh when the token is already expired or within the next hour.
    if expires_at > int(now.timestamp()) + 3600:
        return credentials, False

    refresh_token = credentials.get("refresh_token")
    if not refresh_token:
        raise RuntimeError("Strava credentials missing refresh_token")

    resp = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()

    updated = dict(credentials)
    updated["access_token"] = payload["access_token"]
    updated["refresh_token"] = payload["refresh_token"]
    updated["expires_at"] = int(payload["expires_at"])
    updated["expires_in"] = int(payload.get("expires_in") or 0)
    athlete = payload.get("athlete")
    if athlete:
        updated["athlete"] = athlete
    return updated, True


def fetch_athlete_api(access_token: str) -> dict:
    """Fetch the currently authorized Strava athlete profile."""

    resp = requests.get(
        STRAVA_ATHLETE_API,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_activities_api(
    access_token: str,
    from_date: str,
    to_date: str | None = None,
    *,
    page_size: int = 100,
) -> tuple[list[dict], list[dict]]:
    """Fetch Strava activities and convert them to canonical activity rows."""

    from_day = datetime.strptime(from_date, "%Y-%m-%d").date()
    after_ts = int(
        (
            datetime.combine(from_day, datetime.min.time(), tzinfo=timezone.utc)
            - timedelta(days=1)
        ).timestamp()
    )
    before_ts = None
    if to_date:
        to_day = datetime.strptime(to_date, "%Y-%m-%d").date()
        before_ts = int(
            (
                datetime.combine(to_day, datetime.max.time(), tzinfo=timezone.utc)
                + timedelta(days=1)
            )
            .timestamp()
        )

    rows: list[dict] = []
    raw_activities: list[dict] = []
    page = 1

    while True:
        params = {"after": after_ts, "page": page, "per_page": page_size}
        if before_ts is not None:
            params["before"] = before_ts

        resp = requests.get(
            STRAVA_ACTIVITIES_API,
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break

        for activity in batch:
            parsed = _parse_activity(activity)
            local_date = parsed.get("date") or ""
            if local_date and local_date < from_date:
                continue
            if to_date and local_date and local_date > to_date:
                continue
            rows.append(parsed)
            raw_activities.append(activity)

        if len(batch) < page_size:
            break
        page += 1

    return rows, raw_activities


def fetch_activity_laps(activity_id: str, access_token: str) -> list[dict]:
    """Fetch per-lap Strava split data for one activity."""

    resp = requests.get(
        STRAVA_ACTIVITY_LAPS_API.format(activity_id=activity_id),
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    resp.raise_for_status()

    rows: list[dict] = []
    for idx, lap in enumerate(resp.json(), start=1):
        distance_m = float(lap.get("distance") or 0)
        duration_sec = float(lap.get("moving_time") or lap.get("elapsed_time") or 0)
        distance_km = round(distance_m / 1000, 3) if distance_m > 0 else 0.0
        avg_pace_sec_km = round(duration_sec / distance_km, 1) if distance_km > 0 and duration_sec > 0 else None

        rows.append(
            {
                "activity_id": str(activity_id),
                "split_num": str(idx),
                "distance_km": str(distance_km),
                "duration_sec": str(duration_sec),
                "avg_power": _round_or_empty(lap.get("average_watts")),
                "avg_hr": _round_or_empty(lap.get("average_heartrate")),
                "max_hr": _round_or_empty(lap.get("max_heartrate")),
                "avg_cadence": _round_or_empty(lap.get("average_cadence")),
                "avg_pace_sec_km": _round_or_empty(avg_pace_sec_km),
                "elevation_change_m": _round_or_empty(lap.get("total_elevation_gain")),
            }
        )

    return rows


def _parse_activity(activity: dict) -> dict:
    """Convert one Strava summary activity to the repo's canonical row shape."""

    start_utc = str(activity.get("start_date") or "")
    start_local = str(activity.get("start_date_local") or start_utc)
    sport_type = str(activity.get("sport_type") or activity.get("type") or "")
    distance_m = float(activity.get("distance") or 0)
    duration_sec = float(activity.get("moving_time") or activity.get("elapsed_time") or 0)
    avg_pace_sec_km = round(duration_sec / (distance_m / 1000), 1) if distance_m > 0 and duration_sec > 0 else None

    return {
        "activity_id": str(activity.get("id") or ""),
        "date": start_local[:10],
        "start_time": start_utc,
        "activity_type": _map_activity_type(sport_type),
        "distance_km": str(round(distance_m / 1000, 3)) if distance_m > 0 else "",
        "duration_sec": str(duration_sec) if duration_sec > 0 else "",
        "avg_power": _round_or_empty(activity.get("average_watts")),
        "max_power": _round_or_empty(activity.get("max_watts")),
        "avg_hr": _round_or_empty(activity.get("average_heartrate")),
        "max_hr": _round_or_empty(activity.get("max_heartrate")),
        "avg_pace_sec_km": _round_or_empty(avg_pace_sec_km),
        "elevation_gain_m": _round_or_empty(activity.get("total_elevation_gain")),
        "avg_cadence": _round_or_empty(activity.get("average_cadence")),
        "source": "strava",
    }


def _map_activity_type(raw_type: str) -> str:
    """Normalize Strava sport types to the repo's canonical activity types."""

    key = raw_type.replace(" ", "").replace("_", "").lower()
    return _SPORT_TYPE_MAP.get(key, "other")


def _round_or_empty(val: float | int | None, decimals: int = 1) -> str:
    """Round a numeric value to N decimals, or return empty string if missing."""

    if val in (None, ""):
        return ""
    return str(round(float(val), decimals))
