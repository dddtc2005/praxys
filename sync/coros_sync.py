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
import io
import json
import logging
import random
import time
from datetime import datetime, timezone

import fitparse
import fitparse.base
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
    100: "running",       # outdoor run
    101: "treadmill",     # indoor run / treadmill
    102: "trail_running",
    103: "running",       # track run
    104: "hiking",
    200: "cycling",       # outdoor cycling
    201: "cycling",       # indoor cycling
    300: "swimming",      # pool swim
    301: "swimming",      # open water
    400: "cardio",        # indoor cardio / gym
    402: "strength",
    500: "skiing",
    900: "walking",
    1000: "badminton",
    10000: "triathlon",
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
    """Fetch activity list via GET /activity/query with pagination."""
    url = f"{_base_url(region)}/activity/query"
    all_activities: list[dict] = []
    page = 1

    while True:
        params: dict = {"size": page_size, "pageNumber": page}
        if from_date:
            params["startDay"] = from_date.replace("-", "")
        if to_date:
            params["endDay"] = to_date.replace("-", "")

        resp = requests.get(
            url,
            params=params,
            headers=_headers(access_token),
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()

        result_code = str(body.get("result", ""))
        if result_code not in ("0000", "0"):
            msg = body.get("message", result_code)
            if "token" in str(msg).lower() or "auth" in str(msg).lower():
                raise RuntimeError(f"COROS auth error: {msg}")
            logger.warning("COROS activity query error: %s", msg)
            return []

        data = body.get("data", {})
        activities = data.get("dataList") or data.get("activities") or []
        if not activities:
            break
        all_activities.extend(activities)

        total_pages = data.get("totalPage") or 0
        if page >= total_pages:
            break
        page += 1

    return all_activities


def fetch_activity_detail(
    access_token: str, region: str, activity_id: str,
    sport_type: int | None = None,
) -> bytes:
    """Download a FIT file for the given activity and return raw bytes.

    Uses ``POST /activity/detail/download?labelId=...&sportType=...&fileType=4``
    which returns a JSON response containing ``data.fileUrl``.  We then GET that
    URL to retrieve the actual FIT binary.

    Returns empty bytes on any error so callers can skip gracefully.
    """
    url = f"{_base_url(region)}/activity/detail/download"
    params: dict = {
        "labelId": activity_id,
        "fileType": 4,  # FIT format
    }
    if sport_type is not None:
        params["sportType"] = sport_type

    try:
        resp = requests.post(
            url,
            params=params,
            headers=_headers(access_token),
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as e:
        logger.warning("COROS FIT download request failed for %s: %s", activity_id, e)
        return b""

    if str(body.get("result")) not in ("0000", "0"):
        msg = body.get("message", body.get("result"))
        if "token" in str(msg).lower() or "auth" in str(msg).lower():
            raise RuntimeError(f"COROS auth error: {msg}")
        logger.warning("COROS FIT download error for %s: %s", activity_id, msg)
        return b""

    file_url = (body.get("data") or {}).get("fileUrl")
    if not file_url:
        logger.warning("COROS FIT download: no fileUrl for %s", activity_id)
        return b""

    try:
        fit_resp = requests.get(file_url, timeout=60)
        fit_resp.raise_for_status()
        return fit_resp.content
    except Exception as e:
        logger.warning("COROS FIT file download failed for %s: %s", activity_id, e)
        return b""


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
            msg = raw.get("message", raw.get("result"))
            if "token" in str(msg).lower() or "auth" in str(msg).lower():
                raise RuntimeError(f"COROS auth error: {msg}")
            logger.warning("COROS dayDetail error: %s", msg)
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
        logger.debug("COROS raw activity: sportType=%s name=%s date=%s",
                     a.get("sportType"), a.get("name"), a.get("date") or a.get("day"))
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


def parse_fit_laps(activity_id: str, fit_bytes: bytes) -> list[dict]:
    """Parse lap data from a FIT file into canonical split rows."""
    if not fit_bytes:
        return []

    rows = []
    try:
        fit = fitparse.FitFile(io.BytesIO(fit_bytes))
        idx = 0
        for msg in fit.get_messages("lap"):
            try:
                fields = {f.name: f.value for f in msg.fields}
            except Exception:
                continue
            idx += 1
            distance_m = float(fields.get("total_distance") or 0)
            duration_sec = float(fields.get("total_elapsed_time") or 0)
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
                "avg_power": _round_or_empty(fields.get("avg_power")),
                "avg_hr": _round_or_empty(fields.get("avg_heart_rate"), 0),
                "max_hr": _round_or_empty(fields.get("max_heart_rate"), 0),
                "avg_cadence": _round_or_empty(fields.get("avg_cadence"), 0),
                "avg_pace_sec_km": _round_or_empty(avg_pace_sec_km),
                "elevation_change_m": _round_or_empty(fields.get("total_ascent")),
            })
    except Exception as e:
        logger.warning("FIT lap parse failed for %s: %s", activity_id, e)

    return rows


_SEMICIRCLE_TO_DEG = 180.0 / (2 ** 31)


# ---------------------------------------------------------------------------
# Patch fitparse to tolerate field-size mismatches in COROS FIT files.
#
# COROS firmware sometimes emits fields whose byte size doesn't match the
# declared base type (e.g. 1 byte marked as uint32). Stock fitparse raises
# FitParseError for these. The fitparse source even has a comment saying
# "we could fall back to byte encoding". We apply that fallback here by
# replacing _parse_definition_message with a version that uses
# BASE_TYPE_BYTE when (field_size % base_type.size) != 0.
# ---------------------------------------------------------------------------
def _install_fitparse_lenient_patch():
    from fitparse.base import (
        BASE_TYPE_BYTE, BASE_TYPES, MESSAGE_TYPES,
        FieldDefinition, DevFieldDefinition, DefinitionMessage,
    )
    try:
        from fitparse.base import get_dev_type
    except ImportError:
        get_dev_type = None

    def _lenient_parse_definition_message(self, header):
        endian = '>' if self._read_struct('xB') else '<'
        global_mesg_num, num_fields = self._read_struct('HB', endian=endian)
        mesg_type = MESSAGE_TYPES.get(global_mesg_num)
        field_defs = []

        for _n in range(num_fields):
            field_def_num, field_size, base_type_num = self._read_struct('3B', endian=endian)
            field = mesg_type.fields.get(field_def_num) if mesg_type else None
            base_type = BASE_TYPES.get(base_type_num, BASE_TYPE_BYTE)

            if (field_size % base_type.size) != 0:
                base_type = BASE_TYPE_BYTE  # fall back instead of raising

            if field and field.components:
                for component in field.components:
                    if component.accumulate:
                        accumulators = self._accumulators.setdefault(global_mesg_num, {})
                        accumulators[component.def_num] = 0

            field_defs.append(FieldDefinition(
                field=field,
                def_num=field_def_num,
                base_type=base_type,
                size=field_size,
            ))

        dev_field_defs = []
        if header.is_developer_data:
            num_dev_fields = self._read_struct('B', endian=endian)
            for _n in range(num_dev_fields):
                field_def_num, field_size, dev_data_index = self._read_struct('3B', endian=endian)
                field = get_dev_type(dev_data_index, field_def_num) if get_dev_type else None
                dev_field_defs.append(DevFieldDefinition(
                    field=field,
                    dev_data_index=dev_data_index,
                    def_num=field_def_num,
                    size=field_size,
                ))

        def_mesg = DefinitionMessage(
            header=header,
            endian=endian,
            mesg_type=mesg_type,
            mesg_num=global_mesg_num,
            field_defs=field_defs,
            dev_field_defs=dev_field_defs,
        )
        self._local_mesgs[header.local_mesg_num] = def_mesg
        return def_mesg

    fitparse.base.FitFile._parse_definition_message = _lenient_parse_definition_message


_install_fitparse_lenient_patch()


def parse_fit_stream(activity_id: str, fit_bytes: bytes) -> list[dict]:
    """Parse per-second record data from a FIT file into canonical sample rows."""
    if not fit_bytes:
        return []

    samples = []
    try:
        fit = fitparse.FitFile(io.BytesIO(fit_bytes))
        for msg in fit.get_messages("record"):
            try:
                fields = {f.name: f.value for f in msg.fields}
            except Exception:
                continue
            ts = fields.get("timestamp")
            if ts is None:
                continue
            # Convert datetime to Unix epoch
            if isinstance(ts, datetime):
                t_sec = int(ts.replace(tzinfo=timezone.utc).timestamp()) if ts.tzinfo is None else int(ts.timestamp())
            else:
                t_sec = int(float(ts))

            lat_sc = fields.get("position_lat")
            lng_sc = fields.get("position_long")
            lat = lat_sc * _SEMICIRCLE_TO_DEG if lat_sc is not None else None
            lng = lng_sc * _SEMICIRCLE_TO_DEG if lng_sc is not None else None

            samples.append({
                "activity_id": str(activity_id),
                "source": "coros",
                "t_sec": t_sec,
                "hr_bpm": fields.get("heart_rate"),
                "cadence_spm": fields.get("cadence"),
                "speed_ms": fields.get("speed"),
                "altitude_m": fields.get("altitude"),
                "lat": round(lat, 7) if lat is not None else None,
                "lng": round(lng, 7) if lng is not None else None,
                "power_watts": fields.get("power"),
            })
    except Exception as e:
        logger.warning("FIT record parse failed for %s: %s", activity_id, e)

    return samples


def parse_splits(activity_id: str, detail: dict) -> list[dict]:
    """Parse per-lap split data from activity detail response.

    DEPRECATED: Use parse_fit_laps() with FIT file bytes instead.
    Kept for backward compatibility with non-FIT code paths.
    """
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


def parse_activity_stream(activity_id: str, detail: dict) -> list[dict]:
    """Parse per-second stream data from a COROS activity detail response.

    DEPRECATED: Use parse_fit_stream() with FIT file bytes instead.
    Kept for backward compatibility with non-FIT code paths.

    Returns an empty list when trackPoints is absent (older firmware, activity type
    that doesn't record per-second data, or API shape differs from expectation).
    """
    track_points = detail.get("trackPoints") or detail.get("trackingPoints") or []
    if not track_points:
        return []

    samples = []
    for pt in track_points:
        ts = pt.get("timestamp") or pt.get("utcTime") or pt.get("time")
        if ts is None:
            continue
        lat = pt.get("latitude") or pt.get("lat")
        lng = pt.get("longitude") or pt.get("lon") or pt.get("lng")
        speed_ms = pt.get("speed")
        samples.append({
            "activity_id": str(activity_id),
            "source": "coros",
            "t_sec": int(float(ts)),
            "hr_bpm": pt.get("heartRate") or pt.get("hr"),
            "cadence_spm": pt.get("cadence"),
            "speed_ms": speed_ms,
            "altitude_m": pt.get("altitude") or pt.get("alt"),
            "lat": float(lat) if lat is not None else None,
            "lng": float(lng) if lng is not None else None,
            "power_watts": pt.get("power"),
        })

    return samples


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
