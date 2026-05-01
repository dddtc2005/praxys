"""Oura Ring API v2 integration — fetch/parse layer for the sync API route."""
import requests

OURA_BASE = "https://api.ouraring.com/v2/usercollection"


def _fetch_paginated(url: str, token: str, start_date: str, end_date: str) -> list[dict]:
    """Pull every page from a date-range Oura collection endpoint."""
    headers = {"Authorization": f"Bearer {token}"}
    params = {"start_date": start_date, "end_date": end_date}
    all_data: list[dict] = []
    while True:
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        body = resp.json()
        all_data.extend(body.get("data", []))
        next_token = body.get("next_token")
        if not next_token:
            break
        params["next_token"] = next_token
    return all_data


def fetch_sleep_data(token: str, start_date: str, end_date: str) -> list[dict]:
    """Fetch detailed sleep records (one row per sleep period) from Oura API v2.

    Used for HRV / RHR / total-sleep / deep-sleep extraction. Does NOT
    contain the daily sleep score — that lives at /daily_sleep, which
    `fetch_daily_sleep_data` handles separately.
    """
    return _fetch_paginated(f"{OURA_BASE}/sleep", token, start_date, end_date)


def fetch_daily_sleep_data(token: str, start_date: str, end_date: str) -> list[dict]:
    """Fetch daily sleep score records from Oura API v2.

    Each record represents Oura's once-per-day sleep score (0–100) with
    contributors. Distinct from `/sleep` (which holds per-sleep-period
    detail with no top-level score) and from `/daily_readiness` (which
    holds the readiness score). Without this, the dashboard's "Sleep"
    cell would conflate readiness with sleep.
    """
    return _fetch_paginated(f"{OURA_BASE}/daily_sleep", token, start_date, end_date)


def fetch_readiness_data(token: str, start_date: str, end_date: str) -> list[dict]:
    """Fetch daily readiness records from Oura API."""
    return _fetch_paginated(f"{OURA_BASE}/daily_readiness", token, start_date, end_date)


def parse_sleep_records(raw_records: list[dict]) -> list[dict]:
    """Transform Oura `/sleep` (detailed) API response into our CSV schema.

    Note: this endpoint does NOT carry a sleep score — the `readiness`
    sub-object on each record is Oura's per-sleep-period readiness
    contribution, NOT a sleep quality score. The actual daily sleep
    score comes from `/daily_sleep` via `parse_daily_sleep_records`.
    Earlier code put `r.readiness.score` here as `sleep_score`, which
    surfaced the readiness number in the dashboard's "Sleep" cell.
    """
    rows = []
    for r in raw_records:
        rows.append({
            "date": r.get("day", ""),
            "total_sleep_sec": str(r.get("total_sleep_duration", "")),
            "deep_sleep_sec": str(r.get("deep_sleep_duration", "")),
            "rem_sleep_sec": str(r.get("rem_sleep_duration", "")),
            "light_sleep_sec": str(r.get("light_sleep_duration", "")),
            "efficiency": str(r.get("efficiency", "")),
        })
    return rows


def parse_daily_sleep_records(raw_records: list[dict]) -> list[dict]:
    """Transform Oura `/daily_sleep` API response into our CSV schema.

    The `score` field is the daily sleep score (0–100). Joined back to
    the per-day rows by `date` in the writer so each day gets exactly
    one sleep_score even when `/sleep` returned multiple sleep periods
    (long_sleep + naps).
    """
    rows = []
    for r in raw_records:
        rows.append({
            "date": r.get("day", ""),
            "sleep_score": str(r.get("score", "")),
        })
    return rows


def parse_readiness_records(raw_records: list[dict]) -> list[dict]:
    """Transform Oura readiness API response into our CSV schema."""
    rows = []
    for r in raw_records:
        rows.append({
            "date": r.get("day", ""),
            "readiness_score": str(r.get("score", "")),
            "hrv_avg": "",
            "resting_hr": "",
            "body_temperature_delta": str(r.get("temperature_deviation", "")),
        })
    return rows


def select_oura_hrv_per_day(sleep_raw: list[dict]) -> dict[str, dict]:
    """Pick one HRV/RHR pair per Oura day from possibly-multiple sleep records.

    A single Oura `day` can have several sleep records (`long_sleep`,
    `late_nap`, `rest`), and naps frequently come back with
    ``average_hrv: null``. Naive last-write-wins on the dict lets a nap
    clobber the long_sleep's valid HRV — that's the production data-loss
    path that strands recovery analysis on "Insufficient HRV data".

    Selection rule:
      1. Records with a positive ``average_hrv`` always win over records
         without (regardless of ``type``).
      2. Among records that all have positive HRV, ``long_sleep`` wins
         over naps / rests / unset types.
      3. Within the same priority, first-seen wins (stable for callers
         iterating Oura's response order).

    Returns a ``{day: {"hrv_avg": str, "resting_hr": str, "_type": str}}``
    dict matching the contract the writer expects.
    """
    def _pos_or_none(v) -> float | None:
        try:
            if v in (None, "", "None"):
                return None
            f = float(v)
            return f if f > 0 else None
        except (TypeError, ValueError):
            return None

    selected: dict[str, dict] = {}
    for r in sleep_raw:
        day = r.get("day") or ""
        if not day:
            continue
        candidate = {
            "hrv_avg": str(r.get("average_hrv", "") or ""),
            "resting_hr": str(r.get("average_heart_rate", "") or ""),
            "_type": r.get("type") or "",
        }
        existing = selected.get(day)
        if existing is None:
            selected[day] = candidate
            continue
        existing_hrv = _pos_or_none(existing.get("hrv_avg"))
        candidate_hrv = _pos_or_none(candidate.get("hrv_avg"))
        if candidate_hrv is not None and existing_hrv is None:
            selected[day] = candidate
        elif candidate_hrv is not None and existing_hrv is not None:
            if existing.get("_type") != "long_sleep" and candidate.get("_type") == "long_sleep":
                selected[day] = candidate
    return selected
