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
