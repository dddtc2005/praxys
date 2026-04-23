"""Third probe: discover the grant_type diauth.garmin.cn accepts.

Probe 2 established that ``diauth.garmin.cn`` exists (HTTP 400 with
``unsupported_grant_type``). The library hardcodes
``grant_type=https://connectapi.garmin.com/di-oauth2-service/oauth/grant/service_ticket``;
our probe used the ``.cn`` variant and got rejected. We need to find
which grant_type CN accepts.

Strategy: POST the same form with several grant_type candidates and see
which one stops producing ``unsupported_grant_type``. A different error
(``invalid_grant`` / ``invalid_request`` / 401) proves the grant_type was
recognized — it means the ticket failed the next validation step, which
we expect because our ticket is fake.

Usage:

    .venv/Scripts/python.exe scripts/garmin_cn_api_probe3.py

No creds needed (we only test grant_type, not a real auth).
"""
from __future__ import annotations

import base64
import os
import sys
from typing import Any

sys.path.insert(0, os.getcwd())

try:
    from curl_cffi import requests as cffi_requests  # noqa: F401
    SESS = cffi_requests.Session(impersonate="chrome")
except ImportError:
    import requests  # noqa: F401
    SESS = requests.Session()

URL = "https://diauth.garmin.cn/di-oauth2-service/oauth/token"

GRANT_CANDIDATES = [
    # The library's current value (points at .com) — try it verbatim on CN
    "https://connectapi.garmin.com/di-oauth2-service/oauth/grant/service_ticket",
    # CN-domain variant
    "https://connectapi.garmin.cn/di-oauth2-service/oauth/grant/service_ticket",
    # Bare service_ticket alias
    "service_ticket",
    # Standard OAuth2 grant types
    "authorization_code",
    "client_credentials",
    "password",
    "refresh_token",
    # urn: forms (CAS-style)
    "urn:ietf:params:oauth:grant-type:service-ticket",
    "urn:garmin:grant-type:service_ticket",
]

# Try several client_ids, since some are 2025Q2, some legacy
CLIENT_IDS = [
    "GARMIN_CONNECT_MOBILE_ANDROID_DI_2025Q2",
    "GARMIN_CONNECT_MOBILE_ANDROID_DI_2024Q4",
    "GARMIN_CONNECT_MOBILE_ANDROID_DI",
    "GARMIN_CONNECT_MOBILE_IOS_DI",
]


def _snippet(resp: Any) -> str:
    try:
        body = resp.text
    except Exception:
        body = resp.content.decode("utf-8", "replace")
    return body.replace("\n", " ")[:200]


def _probe(grant_type: str, client_id: str) -> str:
    auth = "Basic " + base64.b64encode(f"{client_id}:".encode()).decode()
    try:
        r = SESS.request(
            "POST", URL,
            headers={
                "Authorization": auth,
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "GCM-Android-5.23",
            },
            data={
                "client_id": client_id,
                "service_ticket": "ST-0-probe-to-discover-grant-type",
                "grant_type": grant_type,
                "service_url": "https://connect.garmin.cn/app",
            },
            timeout=20,
        )
        return f"{r.status_code} {_snippet(r)}"
    except Exception as e:
        return f"EXC {type(e).__name__}: {str(e)[:120]}"


print(f"POST {URL}\n")
print(f"{'grant_type':75}  {'client_id':45}  status/body")
print("-" * 150)

# First, sweep grant_types with the newest client_id (compact table)
for gt in GRANT_CANDIDATES:
    result = _probe(gt, CLIENT_IDS[0])
    print(f"{gt[:75]:75}  {CLIENT_IDS[0][:45]:45}  {result[:300]}")

# If none of those worked, try the sibling client_ids with the CN grant
print("\n--- sweep client_id with the CN grant_type ---")
cn_grant = GRANT_CANDIDATES[1]
for cid in CLIENT_IDS:
    result = _probe(cn_grant, cid)
    print(f"{cn_grant[:75]:75}  {cid[:45]:45}  {result[:300]}")
