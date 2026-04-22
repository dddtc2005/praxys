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
