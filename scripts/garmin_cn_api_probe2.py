"""Second probe: where does CN's API actually live, and does diauth.garmin.cn
exist as a DI token issuer?

The first probe established:
  * connect.garmin.cn/modern/ accepts JWT_WEB (warmup -> 200)
  * connectapi.garmin.cn/<anything> 403s regardless of session/UA/cookies
  * 403 body is {"message":"HTTP 403 Forbidden","error":"ForbiddenException"}
    — application-layer, not Cloudflare

Two hypotheses to test:

1. **Proxy pattern**: CN may expose the same services through
   ``connect.garmin.cn/modern/proxy/<service>/<path>`` (the garth 0.5.x
   era used this) and/or ``connect.garmin.cn/proxy/<service>/<path>``.
   If JWT_WEB works there, we can switch our API base for CN and leave
   the rest of the library untouched.

2. **CN-side diauth**: ``diauth.garmin.cn`` may mirror
   ``diauth.garmin.com``. If the DI token exchange succeeds there, we
   can patch the constant and produce real Bearer tokens that
   authenticate ``connectapi.garmin.cn``.

Usage (from project root, venv active):

    GARMIN_EMAIL=... GARMIN_PASSWORD=... \\
        .venv/Scripts/python.exe scripts/garmin_cn_api_probe2.py
"""
from __future__ import annotations

import base64
import os
import sys
import tempfile
from typing import Any

sys.path.insert(0, os.getcwd())

EMAIL = os.environ.get("GARMIN_EMAIL") or os.environ.get("GARMIN_CN_EMAIL")
PASSWORD = (
    os.environ.get("GARMIN_PASSWORD") or os.environ.get("GARMIN_CN_PASSWORD")
)
if not EMAIL or not PASSWORD:
    sys.exit("Set GARMIN_EMAIL and GARMIN_PASSWORD env vars before running.")

from garminconnect import Garmin  # noqa: E402
from api.routes.sync import _login_garmin_with_cn_fallback  # noqa: E402

client = Garmin(EMAIL, PASSWORD, is_cn=True)
with tempfile.TemporaryDirectory() as d:
    _login_garmin_with_cn_fallback(
        client, {"email": EMAIL, "password": PASSWORD}, d,
    )

inner = client.client
assert inner.jwt_web, "portal fallback did not set jwt_web"

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def _snippet(resp: Any) -> str:
    try:
        body = resp.text
    except Exception:
        body = resp.content.decode("utf-8", "replace")
    body = body.replace("\n", " ").replace("\r", " ")[:220]
    is_cf = "cloudflare" in body.lower() or "attention required" in body.lower()
    return f"{body}{' [CLOUDFLARE]' if is_cf else ''}"


# -------- Hypothesis 1: proxy endpoints on connect.garmin.cn -------------

ENDPOINTS = [
    "/userprofile-service/socialProfile",
    "/activitylist-service/activities/search/activities"
    "?start=0&limit=5&startDate=2026-04-16&endDate=2026-04-23",
]

BASES = [
    # (label, URL prefix, headers-template)
    ("proxy-root", "https://connect.garmin.cn/proxy"),
    ("proxy-modern", "https://connect.garmin.cn/modern/proxy"),
    ("connectapi-with-connect-referer",
     "https://connectapi.garmin.cn"),
]

BASE_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "NK": "NT",
    "User-Agent": BROWSER_UA,
    "Origin": "https://connect.garmin.cn",
    "Referer": "https://connect.garmin.cn/modern/",
}

for label, base in BASES:
    print(f"\n===== {label}: {base} =====")
    for ep in ENDPOINTS:
        url = base + ep
        try:
            resp = inner.cs.request(
                "GET", url, headers=BASE_HEADERS, timeout=30,
            )
            print(f"  GET {ep[:60]}")
            print(f"    status: {resp.status_code}")
            print(f"    body:   {_snippet(resp)}")
        except Exception as e:
            print(f"  GET {ep[:60]} -> EXC {type(e).__name__}: {e}")


# -------- Hypothesis 2: does diauth.garmin.cn exist? ---------------------
#
# We don't have a fresh service ticket handy (portal login consumed ours
# during the redirect). What we can do instead is GET the diauth.garmin.cn
# token URL and see how the server responds — 404/DNS error = endpoint
# doesn't exist; 400/405 = endpoint exists but we sent no payload; 401 =
# exists, auth expected. Any response at all tells us the host is
# reachable and the fix approach is viable.

print("\n===== Diauth CN endpoint reachability =====")
CN_DI_URLS = [
    "https://diauth.garmin.cn/di-oauth2-service/oauth/token",
    "https://diauth.garmin.com.cn/di-oauth2-service/oauth/token",
]

# Use a bare POST with an empty-ish body — we just want to see the host react.
# If the host doesn't exist at all, we'll get DNS / SSL error.
for url in CN_DI_URLS:
    try:
        # Tiny payload so we don't accidentally authenticate anything
        resp = inner.cs.request(
            "POST", url,
            headers={
                "Authorization": "Basic " + base64.b64encode(
                    b"GARMIN_CONNECT_MOBILE_ANDROID_DI_2025Q2:",
                ).decode(),
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "GCM-Android-5.23",
            },
            data={
                "client_id": "GARMIN_CONNECT_MOBILE_ANDROID_DI_2025Q2",
                "service_ticket": "ST-0-probe-to-see-if-host-exists",
                "grant_type": (
                    "https://connectapi.garmin.cn/di-oauth2-service/oauth/grant/service_ticket"
                ),
                "service_url": "https://connect.garmin.cn/app",
            },
            timeout=20,
        )
        print(f"  POST {url}")
        print(f"    status: {resp.status_code}")
        print(f"    body:   {_snippet(resp)}")
    except Exception as e:
        print(f"  POST {url} -> EXC {type(e).__name__}: {str(e)[:160]}")
