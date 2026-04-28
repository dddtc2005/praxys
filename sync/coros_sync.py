"""COROS Training Hub API integration — login, fetch, and parse layer.

Based on the reverse-engineered COROS Training Hub web API (community docs).
Auth uses email + MD5(password). Access tokens have a ~24h TTL and are
refreshed by re-login (no refresh_token flow).

Mobile API (apicn.coros.com) is used for sleep data which is not available
through the Training Hub API.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import time
from datetime import datetime, timezone

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

logger = logging.getLogger(__name__)

BASE_URLS = {
    "eu": "https://teameuapi.coros.com",
    "us": "https://teamapi.coros.com",
    "cn": "https://teamcnapi.coros.com",
}

MOBILE_BASE_URLS = {
    "eu": "https://apieu.coros.com",
    "us": "https://api.coros.com",
    "cn": "https://apicn.coros.com",
}

_MOBILE_IV = b"weloop3_2015_03#"

_SPORT_TYPE_MAP = {
    1: "running",
    2: "cycling",
    3: "swimming",
    4: "trail_running",
    5: "skiing",
    6: "hiking",
    7: "walking",
    8: "strength",
    9: "other",
    10: "triathlon",
    100: "running",       # indoor run
    101: "cycling",       # indoor cycling
}

TOKEN_TTL_SECONDS = 23 * 3600  # conservative: treat as expired after 23h


def _base_url(region: str) -> str:
    return BASE_URLS.get(region, BASE_URLS["us"])


def _md5(password: str) -> str:
    return hashlib.md5(password.encode()).hexdigest()


def login(email: str, password: str, region: str = "us") -> dict:
    """Authenticate with COROS and return credential dict.

    Returns ``{access_token, user_id, region, timestamp}`` on success.
    Raises ``RuntimeError`` on auth failure.
    """
    url = f"{_base_url(region)}/account/login"
    resp = requests.post(
        url,
        json={"account": email, "accountType": 2, "pwd": _md5(password)},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("result") != "0000" and data.get("result") != 0:
        raise RuntimeError(f"COROS login failed: {data.get('message', data.get('result', 'unknown'))}")

    token = data.get("data", {}).get("accessToken")
    user_id = data.get("data", {}).get("userId")
    if not token:
        raise RuntimeError("COROS login succeeded but no accessToken in response")

    return {
        "access_token": token,
        "user_id": str(user_id),
        "region": region,
        "timestamp": int(time.time()),
    }


def is_token_valid(creds: dict) -> bool:
    """Check whether the access token is still within its TTL."""
    ts = int(creds.get("timestamp") or 0)
    return (time.time() - ts) < TOKEN_TTL_SECONDS


def refresh_if_needed(creds: dict, email: str, password: str) -> tuple[dict, bool]:
    """Re-login if the token has expired. Returns ``(creds, changed)``."""
    if is_token_valid(creds):
        return creds, False
    region = creds.get("region", "us")
    new_creds = login(email, password, region)
    return new_creds, True


# ---------------------------------------------------------------------------
# Mobile API — sleep data (reverse-engineered from COROS Android APK)
# ---------------------------------------------------------------------------

def _mobile_base_url(region: str) -> str:
    return MOBILE_BASE_URLS.get(region, MOBILE_BASE_URLS["us"])


def _mobile_encrypt(plaintext: str, app_key: str) -> str:
    """AES-128-CBC encrypt credentials for COROS mobile API login.

    1. XOR plaintext bytes with appKey cyclically
    2. PKCS7 pad to 16-byte boundary
    3. AES-128-CBC encrypt (key=appKey UTF-8, IV=weloop3_2015_03#)
    4. Base64 encode
    """
    key_bytes = app_key.encode("utf-8")
    plain_bytes = plaintext.encode("utf-8")

    # XOR with key cyclically
    xored = bytes(b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(plain_bytes))

    # PKCS7 pad
    padder = PKCS7(128).padder()
    padded = padder.update(xored) + padder.finalize()

    # AES-128-CBC encrypt
    cipher = Cipher(algorithms.AES(key_bytes[:16]), modes.CBC(_MOBILE_IV))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()

    return base64.b64encode(ciphertext).decode("utf-8")


def mobile_login(email: str, password: str, region: str = "us") -> dict:
    """Authenticate with COROS mobile API. Returns ``{mobile_access_token, region}``."""
    base = _mobile_base_url(region)
    url = base + "/coros/user/login"
    app_key = str(random.randint(1_000_000_000_000_000, 9_999_999_999_999_999))

    payload = {
        "account": _mobile_encrypt(email, app_key) + "\n",
        "accountType": 2,
        "appKey": app_key,
        "clientType": 1,
        "hasHrCalibrated": 0,
        "kbValidity": 0,
        "pwd": _mobile_encrypt(_md5(password), app_key) + "\n",
        "region": "310|Europe/Berlin|US",
        "skipValidation": False,
    }
    yfheader = json.dumps({
        "appVersion": 1125917087236096,
        "clientType": 1,
        "language": "en-US",
        "mobileName": "sdk_gphone64_arm64,google,Google",
        "releaseType": 1,
        "systemVersion": "13",
        "timezone": 4,
        "versionCode": "404080400",
    }, separators=(",", ":"))
    headers = {
        "content-type": "application/json",
        "accept-encoding": "gzip",
        "user-agent": "okhttp/4.12.0",
        "request-time": str(int(time.time() * 1000)),
        "yfheader": yfheader,
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if str(data.get("result")) not in ("0000", "0"):
        raise RuntimeError(f"COROS mobile login failed: {data.get('message', data.get('result', 'unknown'))}")

    token = data.get("data", {}).get("accessToken")
    if not token:
        raise RuntimeError("COROS mobile login succeeded but no accessToken in response")

    return {
        "mobile_access_token": token,
        "region": region,
        "mobile_timestamp": int(time.time()),
    }


def fetch_sleep(
    mobile_token: str,
    region: str,
    start_day: str,
    end_day: str,
) -> list[dict]:
    """Fetch sleep data from COROS mobile API.

    ``start_day`` / ``end_day`` are YYYY-MM-DD or YYYYMMDD strings.
    """
    base = _mobile_base_url(region)
    url = f"{base}/coros/data/statistic/daily"
    start_int = start_day.replace("-", "")
    end_int = end_day.replace("-", "")

    resp = requests.post(
        url,
        json={
            "allDeviceSleep": 1,
            "dataType": [5],
            "dataVersion": 0,
            "startTime": int(start_int),
            "endTime": int(end_int),
            "statisticType": 1,
        },
        params={"accessToken": mobile_token},
        headers={"Content-Type": "application/json", "accesstoken": mobile_token},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    if str(data.get("result")) not in ("0000", "0"):
        logger.warning("COROS mobile sleep fetch error: %s", data.get("message", data.get("result")))
        return []

    return data.get("data", {}).get("statisticData", {}).get("dayDataList", [])


def _compute_sleep_score(
    total_min: int, deep_min: int, rem_min: int,
    light_min: int = 0, wake_min: int = 0,
) -> int | None:
    """Derive a 0-100 sleep score using COROS official recommended ranges.

    Components and ranges (from COROS documentation):
    - Duration (30%): optimal 6-10h, best around 7-9h
    - Deep sleep % (25%): recommended 16-30%
    - REM sleep % (20%): recommended 11-35%
    - Light sleep % (15%): recommended < 60%
    - Wake time (10%): recommended ≤ 20 min

    Returns None if total_min <= 0.
    """
    if total_min <= 0:
        return None

    # Duration: 100 in sweet spot (420-540 min / 7-9h), ramp down outside
    if 420 <= total_min <= 540:
        dur_score = 100.0
    elif 360 <= total_min < 420:
        dur_score = 50 + (total_min - 360) / 60 * 50      # 6h=50, 7h=100
    elif 540 < total_min <= 600:
        dur_score = 100 - (total_min - 540) / 60 * 20      # 9h=100, 10h=80
    elif total_min < 360:
        dur_score = max(0, total_min / 360 * 50)            # <6h: 0-50
    else:
        dur_score = max(0, 80 - (total_min - 600) / 60 * 30)  # >10h: penalty

    # Deep %: optimal 16-30%
    deep_pct = deep_min / total_min * 100
    if 16 <= deep_pct <= 30:
        deep_score = 100.0
    elif deep_pct < 16:
        deep_score = deep_pct / 16 * 100
    else:
        deep_score = max(50, 100 - (deep_pct - 30) * 2)    # >30%: mild penalty

    # REM %: optimal 11-35%
    rem_pct = rem_min / total_min * 100
    if 11 <= rem_pct <= 35:
        rem_score = 100.0
    elif rem_pct < 11:
        rem_score = rem_pct / 11 * 100
    else:
        rem_score = max(50, 100 - (rem_pct - 35) * 2)

    # Light %: recommended < 60%
    light_pct = light_min / total_min * 100 if light_min else 0
    if light_pct <= 55:
        light_score = 100.0
    elif light_pct <= 60:
        light_score = 100 - (light_pct - 55) / 5 * 20      # 55-60%: 100→80
    else:
        light_score = max(0, 80 - (light_pct - 60) * 2)    # >60%: drops

    # Wake time: ≤ 20 min = 100, linear penalty above
    if wake_min <= 20:
        wake_score = 100.0
    elif wake_min <= 60:
        wake_score = 100 - (wake_min - 20) / 40 * 60       # 20-60 min: 100→40
    else:
        wake_score = max(0, 40 - (wake_min - 60))

    score = (
        dur_score * 0.30
        + deep_score * 0.25
        + rem_score * 0.20
        + light_score * 0.15
        + wake_score * 0.10
    )
    return max(0, min(100, round(score)))


def parse_sleep(raw_items: list[dict]) -> list[dict]:
    """Parse mobile API sleep response into per-night rows.

    Each item has ``happenDay``, ``performance``, and a nested ``sleepData``
    dict with durations in **minutes** (``totalSleepTime``, ``deepTime``,
    ``eyeTime`` for REM, ``lightTime``).

    Returns rows with ``{date, total_sleep_sec, deep_sleep_sec, rem_sleep_sec,
    sleep_score, source}``.
    """
    rows = []
    for item in raw_items:
        date_str = _format_date(item.get("happenDay") or item.get("date"))
        if not date_str:
            continue

        sd = item.get("sleepData", {})
        total_min = sd.get("totalSleepTime") or 0
        deep_min = sd.get("deepTime") or 0
        rem_min = sd.get("eyeTime") or 0
        light_min = sd.get("lightTime") or 0
        wake_min = sd.get("wakeTime") or 0

        # COROS mobile API returns performance=-1 (no native sleep score).
        # Derive a 0-100 score from duration and sleep architecture.
        sleep_score = _compute_sleep_score(
            int(total_min), int(deep_min), int(rem_min),
            int(light_min), int(wake_min),
        )

        rows.append({
            "date": date_str,
            "total_sleep_sec": str(int(total_min) * 60) if total_min else "",
            "deep_sleep_sec": str(int(deep_min) * 60) if deep_min else "",
            "rem_sleep_sec": str(int(rem_min) * 60) if rem_min else "",
            "sleep_score": str(sleep_score) if sleep_score is not None else "",
            "source": "coros",
        })
    return rows


def _headers(access_token: str) -> dict:
    return {"accessToken": access_token}


def fetch_activities(
    access_token: str,
    region: str,
    from_date: str,
    to_date: str,
    *,
    page_size: int = 100,
) -> list[dict]:
    """Fetch activity list via POST /activity/query with pagination."""
    url = f"{_base_url(region)}/activity/query"
    all_activities: list[dict] = []
    page = 1

    while True:
        resp = requests.post(
            url,
            json={
                "size": page_size,
                "pageNumber": page,
                "startDay": from_date.replace("-", ""),
                "endDay": to_date.replace("-", ""),
            },
            headers=_headers(access_token),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        activities = data.get("dataList") or data.get("activities") or []
        if not activities:
            break
        all_activities.extend(activities)
        total_count = data.get("totalCount") or data.get("count") or 0
        if len(all_activities) >= total_count or len(activities) < page_size:
            break
        page += 1

    return all_activities


def fetch_activity_detail(
    access_token: str, region: str, activity_id: str,
) -> dict:
    """Fetch detailed activity data (laps, HR zones, power)."""
    url = f"{_base_url(region)}/activity/detail/query"
    resp = requests.post(
        url,
        json={"labelId": activity_id},
        headers=_headers(access_token),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data", {})


def fetch_daily_metrics(
    access_token: str,
    region: str,
    from_date: str,
    to_date: str,
) -> list[dict]:
    """Fetch daily biometric metrics (HRV, resting HR, training load).

    Uses two endpoints:
    - /analyse/dayDetail/query (GET with query params) — up to ~24 weeks of
      daily HRV, RHR, training load
    - /dashboard/query (GET) — last ~7 days of nightly HRV with baseline
    """
    base = _base_url(region)
    hdrs = _headers(access_token)
    all_items: list[dict] = []

    # 1. Daily detail — long-range HRV + RHR + training load
    url = f"{base}/analyse/dayDetail/query"
    params = {
        "startDay": from_date.replace("-", ""),
        "endDay": to_date.replace("-", ""),
    }
    try:
        resp = requests.get(url, params=params, headers=hdrs, timeout=30)
        resp.raise_for_status()
        raw = resp.json()
        if raw.get("result") in ("0000", 0, "0"):
            items = raw.get("data", {}).get("dayList", [])
            logger.debug("COROS dayDetail: %d items", len(items))
            all_items.extend(items)
        else:
            logger.warning("COROS dayDetail error: %s", raw.get("message", raw.get("result")))
    except Exception as e:
        logger.warning("COROS dayDetail fetch failed: %s", e)

    # 2. Dashboard — recent HRV with baseline (fills gaps if dayDetail lacks HRV)
    try:
        resp2 = requests.get(f"{base}/dashboard/query", headers=hdrs, timeout=30)
        resp2.raise_for_status()
        raw2 = resp2.json()
        if raw2.get("result") in ("0000", 0, "0"):
            hrv_data = raw2.get("data", {}).get("summaryInfo", {}).get("sleepHrvData", {})
            hrv_list = hrv_data.get("sleepHrvList", [])
            logger.debug("COROS dashboard HRV: %d items", len(hrv_list))
            # Merge dashboard HRV into daily items by date
            existing_dates = {str(item.get("happenDay", "")) for item in all_items}
            for hrv_item in hrv_list:
                day = str(hrv_item.get("happenDay", ""))
                if day and day not in existing_dates:
                    all_items.append(hrv_item)
    except Exception as e:
        logger.debug("COROS dashboard fetch failed: %s", e)

    return all_items


def fetch_fitness_summary(access_token: str, region: str) -> dict:
    """Fetch fitness summary (VO2max, LTHR, lactate threshold pace)."""
    url = f"{_base_url(region)}/analyse/query"
    resp = requests.get(
        url,
        headers=_headers(access_token),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data", {})


# ---------------------------------------------------------------------------
# Parsers — raw COROS data → canonical row dicts
# ---------------------------------------------------------------------------

def _round_or_empty(val, decimals: int = 1) -> str:
    if val in (None, "", 0):
        return ""
    try:
        f = float(val)
        if decimals == 0:
            return str(int(f))
        return str(round(f, decimals))
    except (TypeError, ValueError):
        return ""


def _format_date(raw: str | int | None) -> str:
    """Convert COROS date formats (YYYYMMDD int or string) to YYYY-MM-DD."""
    if raw is None:
        return ""
    s = str(raw)
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s[:10]


def _map_sport_type(sport_type: int | None) -> str:
    if sport_type is None:
        return "other"
    return _SPORT_TYPE_MAP.get(sport_type, "other")


def parse_activities(raw_activities: list[dict]) -> list[dict]:
    """Convert COROS activity list to canonical activity rows."""
    rows = []
    for a in raw_activities:
        distance_m = float(a.get("distance") or a.get("totalDistance") or 0)
        duration_sec = float(a.get("duration") or a.get("totalTime") or 0)
        distance_km = distance_m / 1000 if distance_m > 0 else 0
        avg_pace_sec_km = (
            round(duration_sec / distance_km, 1)
            if distance_km > 0 and duration_sec > 0
            else None
        )

        start_time = a.get("startTime") or a.get("startTimestamp") or ""
        if isinstance(start_time, (int, float)):
            start_time = datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat()

        date_str = _format_date(a.get("date") or a.get("day"))
        if not date_str and start_time:
            date_str = str(start_time)[:10]

        rows.append({
            "activity_id": str(a.get("labelId") or a.get("activityId") or ""),
            "date": date_str,
            "start_time": str(start_time),
            "activity_type": _map_sport_type(a.get("sportType")),
            "distance_km": str(round(distance_km, 3)) if distance_km > 0 else "",
            "duration_sec": str(duration_sec) if duration_sec > 0 else "",
            "avg_power": _round_or_empty(a.get("avgPower")),
            "max_power": _round_or_empty(a.get("maxPower")),
            "avg_hr": _round_or_empty(a.get("avgHeartRate"), 0),
            "max_hr": _round_or_empty(a.get("maxHeartRate"), 0),
            "avg_pace_sec_km": _round_or_empty(avg_pace_sec_km),
            "elevation_gain_m": _round_or_empty(a.get("totalAscent") or a.get("elevationGain")),
            "avg_cadence": _round_or_empty(a.get("avgCadence"), 0),
            "source": "coros",
        })
    return rows


def parse_splits(activity_id: str, detail: dict) -> list[dict]:
    """Parse per-lap split data from activity detail response."""
    rows = []
    laps = detail.get("lapList") or detail.get("laps") or []
    for idx, lap in enumerate(laps, start=1):
        distance_m = float(lap.get("distance") or 0)
        duration_sec = float(lap.get("duration") or lap.get("totalTime") or 0)
        distance_km = round(distance_m / 1000, 3) if distance_m > 0 else 0.0
        avg_pace_sec_km = (
            round(duration_sec / distance_km, 1)
            if distance_km > 0 and duration_sec > 0
            else None
        )

        rows.append({
            "activity_id": str(activity_id),
            "split_num": str(idx),
            "distance_km": str(distance_km),
            "duration_sec": str(duration_sec),
            "avg_power": _round_or_empty(lap.get("avgPower")),
            "avg_hr": _round_or_empty(lap.get("avgHeartRate"), 0),
            "max_hr": _round_or_empty(lap.get("maxHeartRate"), 0),
            "avg_cadence": _round_or_empty(lap.get("avgCadence"), 0),
            "avg_pace_sec_km": _round_or_empty(avg_pace_sec_km),
            "elevation_change_m": _round_or_empty(lap.get("totalAscent")),
        })
    return rows


def parse_daily_metrics(raw_metrics: list[dict]) -> list[dict]:
    """Parse daily metrics (HRV, resting HR, training load) into recovery/fitness rows.

    Handles field names from both /analyse/dayDetail/query and /dashboard/query:
    - Date: happenDay (YYYYMMDD int), day, or date
    - HRV: avgSleepHrv or hrv
    - RHR: rhr or restingHeartRate
    """
    rows = []
    for m in raw_metrics:
        date_str = _format_date(m.get("happenDay") or m.get("day") or m.get("date"))
        if not date_str:
            continue
        row: dict = {"date": date_str, "source": "coros"}

        hrv = m.get("avgSleepHrv") or m.get("hrv")
        if hrv:
            row["hrv_ms"] = str(round(float(hrv)))

        rhr = m.get("rhr") or m.get("restingHeartRate")
        if rhr:
            row["resting_hr"] = str(round(float(rhr)))

        tl = m.get("trainingLoad")
        if tl:
            row["training_load"] = str(round(float(tl)))

        fatigue = m.get("fatigueRate")
        if fatigue is not None:
            row["fatigue_rate"] = _round_or_empty(fatigue)

        rows.append(row)
    return rows


def parse_fitness_summary(data: dict) -> dict:
    """Extract VO2max, LTHR from fitness summary response."""
    result: dict = {}

    vo2max = data.get("vo2max") or data.get("vo2Max")
    if vo2max:
        try:
            result["vo2max"] = round(float(vo2max), 1)
        except (TypeError, ValueError):
            pass

    lthr = data.get("lthr") or data.get("lactateThresholdHeartRate")
    if lthr:
        try:
            result["lthr_bpm"] = int(float(lthr))
        except (TypeError, ValueError):
            pass

    lt_pace = data.get("lactateThresholdPace") or data.get("ltPace")
    if lt_pace:
        try:
            result["lt_pace_sec_km"] = round(float(lt_pace))
        except (TypeError, ValueError):
            pass

    stamina = data.get("staminaLevel")
    if stamina is not None:
        result["stamina_level"] = _round_or_empty(stamina)

    return result
