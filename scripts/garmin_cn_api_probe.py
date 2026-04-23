"""Probe connectapi.garmin.cn after a JWT_WEB-only login.

The upstream library's ``_run_request`` hands every API call a bare
``requests.Session`` and sets ``Cookie: JWT_WEB=<token>`` explicitly —
no User-Agent, no cookie-jar entries, no TLS fingerprint. On CN that
yields 403. This script tries several header/cookie/session variants
against two small endpoints (``/userprofile-service/socialProfile`` and
``/activitylist-service/activities/search/activities``) and prints the
status + a body snippet for each, so we can tell which knob actually
unblocks the request.

Usage (from project root, venv active):

    GARMIN_EMAIL=... GARMIN_PASSWORD=... \\
        .venv/Scripts/python.exe scripts/garmin_cn_api_probe.py

No creds or cookie *values* are printed — only cookie names and status
codes. Uses a throwaway tempdir for tokens.
"""
from __future__ import annotations

import os
import sys
import tempfile
from typing import Any

# Allow running from the project root without installing the package.
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
print(f"\nPost-login state: jwt_web={bool(inner.jwt_web)} di_token={bool(inner.di_token)}")
print(f"Session type: {type(inner.cs).__name__}")
print("Cookies in session jar (names only):")
for cookie in inner.cs.cookies.jar:
    print(f"  - {cookie.name} (domain={cookie.domain})")

ENDPOINTS = [
    "/userprofile-service/socialProfile",
    "/activitylist-service/activities/search/activities"
    "?start=0&limit=5&startDate=2026-04-16&endDate=2026-04-23",
]

BASE = "https://connectapi.garmin.cn"


def _snippet(resp: Any) -> str:
    try:
        body = resp.text if hasattr(resp, "text") else resp.content.decode("utf-8", "replace")
    except Exception:
        body = "<unreadable>"
    one_line = body.replace("\n", " ").replace("\r", " ")[:200]
    is_cf = "cloudflare" in body.lower() or "attention required" in body.lower()
    tag = " [CLOUDFLARE]" if is_cf else ""
    return f"{one_line}{tag}"


def _probe(label: str, session: Any, headers: dict, use_explicit_cookie: bool):
    print(f"\n===== {label} =====")
    for path in ENDPOINTS:
        url = BASE + path
        h = dict(headers)
        if use_explicit_cookie and inner.jwt_web:
            h["Cookie"] = f"JWT_WEB={inner.jwt_web}"
        try:
            resp = session.request("GET", url, headers=h, timeout=30)
            status = resp.status_code
        except Exception as e:
            print(f"  {path[:60]}... -> EXC {type(e).__name__}: {e}")
            continue
        print(f"  GET {path[:70]}")
        print(f"    status: {status}")
        print(f"    body:   {_snippet(resp)}")


# --- Baseline: library's default path (bare requests.Session + explicit Cookie) ---
import requests  # noqa: E402

_probe(
    "A. Library default: bare requests.Session, explicit Cookie header only",
    requests.Session(),
    {
        "Accept": "application/json",
        "NK": "NT",
        "Origin": "https://connect.garmin.cn",
        "Referer": "https://connect.garmin.cn/modern/",
        "DI-Backend": "connectapi.garmin.cn",
    },
    use_explicit_cookie=True,
)

# --- Variant B: curl_cffi login session, cookie jar only (no explicit Cookie) ---
_probe(
    "B. curl_cffi login session + cookie-jar (no explicit Cookie header)",
    inner.cs,
    {
        "Accept": "application/json",
        "NK": "NT",
        "Origin": "https://connect.garmin.cn",
        "Referer": "https://connect.garmin.cn/modern/",
        "DI-Backend": "connectapi.garmin.cn",
    },
    use_explicit_cookie=False,
)

# --- Variant C: curl_cffi session + browser UA + cookie jar ---
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_probe(
    "C. curl_cffi + browser UA + cookie jar",
    inner.cs,
    {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "NK": "NT",
        "Origin": "https://connect.garmin.cn",
        "Referer": "https://connect.garmin.cn/modern/",
        "DI-Backend": "connectapi.garmin.cn",
        "User-Agent": BROWSER_UA,
    },
    use_explicit_cookie=False,
)

# --- Variant D: curl_cffi + browser UA + cookie jar + CSRF token if present ---
extra = {}
if getattr(inner, "csrf_token", None):
    extra["connect-csrf-token"] = str(inner.csrf_token)
    print(f"\n(Using connect-csrf-token from client.csrf_token)")
else:
    print("\n(No client.csrf_token available; skipping CSRF header)")

_probe(
    "D. C + CSRF header (if available)",
    inner.cs,
    {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "NK": "NT",
        "Origin": "https://connect.garmin.cn",
        "Referer": "https://connect.garmin.cn/modern/",
        "DI-Backend": "connectapi.garmin.cn",
        "User-Agent": BROWSER_UA,
        **extra,
    },
    use_explicit_cookie=False,
)

# --- Variant E: Warm up by first fetching /modern/ on connect.garmin.cn to ---
# seed any cookies that the browser would get after login redirect ---
print("\nWarming up via GET https://connect.garmin.cn/modern/ ...")
try:
    warmup = inner.cs.get(
        "https://connect.garmin.cn/modern/",
        headers={
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            ),
            "User-Agent": BROWSER_UA,
        },
        timeout=30,
    )
    print(f"  warmup status: {warmup.status_code}")
    print("  cookies after warmup:")
    for c in inner.cs.cookies.jar:
        print(f"    - {c.name} (domain={c.domain})")
except Exception as e:
    print(f"  warmup failed: {type(e).__name__}: {e}")

_probe(
    "E. C repeated after warmup (cookies may now include JWT_FGP etc.)",
    inner.cs,
    {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "NK": "NT",
        "Origin": "https://connect.garmin.cn",
        "Referer": "https://connect.garmin.cn/modern/",
        "DI-Backend": "connectapi.garmin.cn",
        "User-Agent": BROWSER_UA,
    },
    use_explicit_cookie=False,
)
