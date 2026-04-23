"""Reproduce GitHub issue #75 — "JWT_WEB cookie not set after ticket
consumption" — and check whether the same library paths work for
international accounts.

Hypothesis: garminconnect 0.3.2's mobile iOS login path hardcodes
``.com`` service URLs (``IOS_SERVICE_URL``, ``DI_TOKEN_URL``) regardless
of the ``Client`` ``domain``. For CN this is fatal; for international it
may or may not matter depending on whether DI exchange returns a usable
Bearer token via the portal path.

This script:
  * Instruments ``requests.Session`` and ``curl_cffi.Session`` to log every
    outbound URL (hostnames + paths; query strings redacted).
  * Runs ``Client(domain=<chosen>).login(...)`` once to capture the real
    end-to-end behaviour.
  * Runs each login strategy individually (mobile+cffi, mobile+requests,
    widget+cffi, portal+cffi, portal+requests) on a fresh ``Client`` so we
    can tell which strategies work on that domain.

Usage (from project root, venv activated):

    # International (default)
    GARMIN_EMAIL=you@example.com GARMIN_PASSWORD=... \\
        .venv/Scripts/python.exe scripts/garmin_cn_repro.py

    # China
    GARMIN_IS_CN=true GARMIN_EMAIL=... GARMIN_PASSWORD=... \\
        .venv/Scripts/python.exe scripts/garmin_cn_repro.py

Legacy ``GARMIN_CN_EMAIL`` / ``GARMIN_CN_PASSWORD`` are still accepted.

No creds or cookie values are printed. Nothing is written to
``sync/.garmin_tokens/`` or the DB.
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from urllib.parse import urlparse

EMAIL = os.environ.get("GARMIN_EMAIL") or os.environ.get("GARMIN_CN_EMAIL")
PASSWORD = (
    os.environ.get("GARMIN_PASSWORD") or os.environ.get("GARMIN_CN_PASSWORD")
)
if not EMAIL or not PASSWORD:
    sys.exit(
        "Set GARMIN_EMAIL and GARMIN_PASSWORD env vars before running "
        "(GARMIN_CN_EMAIL / GARMIN_CN_PASSWORD also accepted)."
    )

IS_CN = os.environ.get("GARMIN_IS_CN", "").strip().lower() in (
    "1", "true", "yes", "y",
)
DOMAIN = "garmin.cn" if IS_CN else "garmin.com"
print(f"Testing domain: {DOMAIN} (set GARMIN_IS_CN=true for CN, unset for .com)")


# --- Outbound URL logger -------------------------------------------------
# Patch Session.request at the class level so every strategy (including
# short-lived local sessions inside curl_cffi) is captured.

call_log: list[dict] = []


def _record(kind: str, method: str, url: str,
            status: int | None = None, error: str | None = None) -> None:
    p = urlparse(url)
    safe_url = f"{p.scheme}://{p.netloc}{p.path}"
    call_log.append({
        "kind": kind, "method": method.upper(),
        "host": p.netloc, "path": p.path,
        "status": status, "error": error,
    })
    tail = f"-> {status}" if status is not None else f"-> {error or '?'}"
    print(f"  [{kind:4s}] {method.upper():4s} {safe_url}  {tail}")


def _wrap_session_class(cls: type, kind: str) -> None:
    orig = cls.request

    def wrapped(self, method, url, *args, **kwargs):  # type: ignore[no-untyped-def]
        try:
            resp = orig(self, method, url, *args, **kwargs)
            _record(kind, method, url, status=getattr(resp, "status_code", None))
            return resp
        except Exception as e:
            _record(kind, method, url, error=f"{type(e).__name__}: {str(e)[:80]}")
            raise

    cls.request = wrapped  # type: ignore[assignment]


import requests  # noqa: E402

_wrap_session_class(requests.Session, "req")

try:
    from curl_cffi import requests as cffi_requests  # noqa: E402

    _wrap_session_class(cffi_requests.Session, "cffi")
    HAS_CFFI = True
except ImportError:
    print("WARNING: curl_cffi not installed — cffi strategies will be skipped")
    HAS_CFFI = False


# --- Run strategies ------------------------------------------------------

from garminconnect.client import Client  # noqa: E402

results: dict[str, tuple[str, int, int]] = {}


def _run(label: str, runner) -> None:
    print(f"\n===== {label} =====")
    start = len(call_log)
    outcome = "ok"
    try:
        runner()
        print("  --> SUCCEEDED")
    except Exception as e:
        outcome = f"{type(e).__name__}: {str(e)[:160]}"
        print(f"  --> FAILED: {outcome}")
    hosts = Counter(e["host"] for e in call_log[start:])
    com = sum(n for h, n in hosts.items() if h.endswith(".garmin.com"))
    cn = sum(n for h, n in hosts.items() if h.endswith(".garmin.cn"))
    print(f"  calls: {len(call_log) - start}  (.com={com}, .cn={cn})")
    results[label] = (outcome, com, cn)


print(f"\n### Default Client.login() on domain={DOMAIN} ###")
c = Client(domain=DOMAIN)
_run("default login()", lambda: c.login(EMAIL, PASSWORD))

if HAS_CFFI:
    print("\n### Individual strategies (fresh Client each) ###")
    strategies = [
        ("mobile+cffi",
         lambda c: c._mobile_login_cffi(EMAIL, PASSWORD)),
        ("mobile+requests",
         lambda c: c._mobile_login_requests(EMAIL, PASSWORD)),
        ("widget+cffi",
         lambda c: c._widget_web_login(EMAIL, PASSWORD)),
        ("portal+cffi",
         lambda c: c._portal_web_login_cffi(EMAIL, PASSWORD)),
        ("portal+requests",
         lambda c: c._portal_web_login_requests(EMAIL, PASSWORD)),
    ]
    for name, runner in strategies:
        client = Client(domain=DOMAIN)
        _run(name, lambda c=client, r=runner: r(c))


# --- Summary -------------------------------------------------------------

print("\n\n===== SUMMARY =====")
for label, (outcome, com, cn) in results.items():
    print(f"  {label:20s}  .com={com:<3d} .cn={cn:<3d}  {outcome}")

all_hosts = Counter(e["host"] for e in call_log)
print("\n--- all hostnames touched (count across whole run) ---")
for host, n in sorted(all_hosts.items(), key=lambda kv: -kv[1]):
    print(f"  {n:4d}  {host}")
