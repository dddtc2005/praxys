"""Oura Ring API v2 integration — fetch/parse layer for the sync API route."""
import requests

OURA_BASE = "https://api.ouraring.com/v2/usercollection"


def fetch_sleep_data(token: str, start_date: str, end_date: str) -> list[dict]:
    """Fetch detailed sleep records from Oura API v2."""
    url = f"{OURA_BASE}/sleep"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"start_date": start_date, "end_date": end_date}
    all_data = []
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


def fetch_readiness_data(token: str, start_date: str, end_date: str) -> list[dict]:
    """Fetch daily readiness records from Oura API."""
    url = f"{OURA_BASE}/daily_readiness"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"start_date": start_date, "end_date": end_date}
    all_data = []
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


def parse_sleep_records(raw_records: list[dict]) -> list[dict]:
    """Transform Oura sleep API response into our CSV schema."""
    rows = []
    for r in raw_records:
        readiness = r.get("readiness") or {}
        rows.append({
            "date": r.get("day", ""),
            "sleep_score": str(readiness.get("score", "")),
            "total_sleep_sec": str(r.get("total_sleep_duration", "")),
            "deep_sleep_sec": str(r.get("deep_sleep_duration", "")),
            "rem_sleep_sec": str(r.get("rem_sleep_duration", "")),
            "light_sleep_sec": str(r.get("light_sleep_duration", "")),
            "efficiency": str(r.get("efficiency", "")),
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
