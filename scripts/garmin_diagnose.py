"""Garmin Connect diagnostic toolkit.

Reproduces and debugs the CN / international sync edge cases documented
in ``docs/dev/gotchas.md`` (Garmin CN section). Pull this out when sync
breaks after a ``garminconnect`` library upgrade, a Garmin-side auth
change, or a new region-specific symptom report (e.g. GitHub issue #75).

Modes:

  login       Instrument ``requests`` + ``curl_cffi``, run the full
              five-strategy login chain and each strategy individually
              against the configured domain, log every outbound URL and
              final outcome. No dependency on ``api.routes.sync`` — it
              talks directly to ``garminconnect.Client``, so it keeps
              working if we ever replace our login helper.

  api         Log in via ``_login_garmin_with_cn_fallback`` (exercising
              the real product path), then hit ``connectapi.garmin.*``
              and ``connect.garmin.*/proxy`` with several header /
              session / base-URL variants. Shows whether the post-login
              auth state actually authorises JSON API calls and
              distinguishes Cloudflare rejections from app-level
              ``ForbiddenException``.

  grants      Sweep OAuth2 ``grant_type`` values against
              ``diauth.garmin.cn`` with a bogus service ticket — no
              credentials required. Used to discover which grant_type
              CN's DI service accepts when rewiring the token exchange.

  all         Run login + api + grants in that order.

Usage (from project root, venv active):

    # Default: all three modes, international account
    GARMIN_EMAIL=... GARMIN_PASSWORD=... \\
        .venv/Scripts/python.exe scripts/garmin_diagnose.py all

    # CN account, just the login-strategy probe
    GARMIN_IS_CN=true GARMIN_EMAIL=... GARMIN_PASSWORD=... \\
        .venv/Scripts/python.exe scripts/garmin_diagnose.py login

    # Grant type sweep only (no creds required)
    .venv/Scripts/python.exe scripts/garmin_diagnose.py grants

Legacy ``GARMIN_CN_EMAIL`` / ``GARMIN_CN_PASSWORD`` env names still
work. No credentials or cookie values are printed; only cookie names,
hostnames, status codes, and response-body snippets.
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
import tempfile
from collections import Counter
from typing import Any, Callable
from urllib.parse import urlparse

# Allow running from project root without `pip install -e .`.
sys.path.insert(0, os.getcwd())

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


# --------------------------------------------------------------------------- #
#  Shared helpers                                                             #
# --------------------------------------------------------------------------- #

def _require_creds() -> tuple[str, str, bool]:
    email = os.environ.get("GARMIN_EMAIL") or os.environ.get("GARMIN_CN_EMAIL")
    password = (
        os.environ.get("GARMIN_PASSWORD") or os.environ.get("GARMIN_CN_PASSWORD")
    )
    if not email or not password:
        sys.exit(
            "Set GARMIN_EMAIL and GARMIN_PASSWORD env vars before running "
            "(GARMIN_CN_EMAIL / GARMIN_CN_PASSWORD also accepted).",
        )
    is_cn = os.environ.get("GARMIN_IS_CN", "").strip().lower() in (
        "1", "true", "yes", "y",
    )
    return email, password, is_cn


def _snippet(resp: Any, limit: int = 200) -> str:
    try:
        body = resp.text
    except Exception:
        body = getattr(resp, "content", b"").decode("utf-8", "replace")
    one_line = body.replace("\n", " ").replace("\r", " ")[:limit]
    is_cf = "cloudflare" in body.lower() or "attention required" in body.lower()
    return f"{one_line}{' [CLOUDFLARE]' if is_cf else ''}"


# --------------------------------------------------------------------------- #
#  Mode: login — five-strategy chain instrumentation                          #
# --------------------------------------------------------------------------- #

def _mode_login(args: argparse.Namespace) -> int:
    email, password, is_cn = _require_creds()
    domain = "garmin.cn" if is_cn else "garmin.com"
    print(f"Testing domain: {domain} (set GARMIN_IS_CN=true for CN)\n")

    call_log: list[dict] = []

    def _record(kind: str, method: str, url: str,
                status: int | None = None, error: str | None = None) -> None:
        p = urlparse(url)
        call_log.append({
            "kind": kind, "method": method.upper(),
            "host": p.netloc, "path": p.path,
        })
        tail = f"-> {status}" if status is not None else f"-> {error or '?'}"
        print(f"  [{kind:4s}] {method.upper():4s} {p.scheme}://{p.netloc}{p.path}  {tail}")

    def _wrap(cls: type, kind: str) -> None:
        orig = cls.request

        def wrapped(self, method, url, *a, **kw):  # type: ignore[no-untyped-def]
            try:
                resp = orig(self, method, url, *a, **kw)
                _record(kind, method, url, status=getattr(resp, "status_code", None))
                return resp
            except Exception as e:
                _record(kind, method, url,
                        error=f"{type(e).__name__}: {str(e)[:80]}")
                raise

        cls.request = wrapped  # type: ignore[assignment]

    import requests

    _wrap(requests.Session, "req")
    try:
        from curl_cffi import requests as cffi_requests

        _wrap(cffi_requests.Session, "cffi")
        has_cffi = True
    except ImportError:
        print("WARNING: curl_cffi not installed — cffi strategies will be skipped")
        has_cffi = False

    from garminconnect.client import Client

    results: dict[str, tuple[str, int, int]] = {}

    def _run(label: str, runner: Callable[[], None]) -> None:
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

    print(f"### Default Client.login() on domain={domain} ###")
    c = Client(domain=domain)
    _run("default login()", lambda: c.login(email, password))

    if has_cffi and not args.default_only:
        print("\n### Individual strategies (fresh Client each) ###")
        strategies: list[tuple[str, Callable[[Client], None]]] = [
            ("mobile+cffi",
             lambda c: c._mobile_login_cffi(email, password)),
            ("mobile+requests",
             lambda c: c._mobile_login_requests(email, password)),
            ("widget+cffi",
             lambda c: c._widget_web_login(email, password)),
            ("portal+cffi",
             lambda c: c._portal_web_login_cffi(email, password)),
            ("portal+requests",
             lambda c: c._portal_web_login_requests(email, password)),
        ]
        for name, runner_fn in strategies:
            fresh = Client(domain=domain)
            _run(name, lambda c=fresh, r=runner_fn: r(c))

    print("\n\n===== SUMMARY =====")
    for label, (outcome, com, cn) in results.items():
        print(f"  {label:20s}  .com={com:<3d} .cn={cn:<3d}  {outcome}")

    all_hosts = Counter(e["host"] for e in call_log)
    print("\n--- hostnames touched (count across whole run) ---")
    for host, n in sorted(all_hosts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  {host}")
    return 0


# --------------------------------------------------------------------------- #
#  Mode: api — post-login endpoint / header variants                           #
# --------------------------------------------------------------------------- #

def _mode_api(args: argparse.Namespace) -> int:
    email, password, is_cn = _require_creds()
    region = "cn" if is_cn else "com"

    from garminconnect import Garmin
    from api.routes.sync import _login_garmin_with_cn_fallback

    client = Garmin(email, password, is_cn=is_cn)
    with tempfile.TemporaryDirectory() as d:
        _login_garmin_with_cn_fallback(
            client, {"email": email, "password": password}, d,
        )

    inner = client.client
    print(f"\nPost-login: di_token={bool(inner.di_token)} "
          f"jwt_web={bool(inner.jwt_web)}")
    print("Cookies in session jar (names + domain only):")
    for cookie in inner.cs.cookies.jar:
        print(f"  - {cookie.name} (domain={cookie.domain})")

    endpoints = [
        "/userprofile-service/socialProfile",
        (
            "/activitylist-service/activities/search/activities"
            "?start=0&limit=5"
        ),
    ]
    bases = [
        ("connectapi",
         f"https://connectapi.garmin.{region}"),
        ("connect/proxy (legacy garth path)",
         f"https://connect.garmin.{region}/proxy"),
        ("connect/modern/proxy",
         f"https://connect.garmin.{region}/modern/proxy"),
    ]
    base_headers = {
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "NK": "NT",
        "User-Agent": BROWSER_UA,
        "Origin": f"https://connect.garmin.{region}",
        "Referer": f"https://connect.garmin.{region}/modern/",
    }

    for label, base in bases:
        print(f"\n===== {label}: {base} =====")
        for ep in endpoints:
            url = base + ep
            try:
                resp = inner.cs.request(
                    "GET", url, headers=base_headers, timeout=30,
                )
                print(f"  GET {ep[:65]}")
                print(f"    status: {resp.status_code}")
                print(f"    body:   {_snippet(resp)}")
            except Exception as e:
                print(f"  GET {ep[:65]} -> EXC {type(e).__name__}: {e}")

    if is_cn or args.probe_diauth_cn:
        print("\n===== diauth.garmin.cn reachability (no real auth) =====")
        try:
            resp = inner.cs.request(
                "POST",
                "https://diauth.garmin.cn/di-oauth2-service/oauth/token",
                headers={
                    "Authorization": "Basic " + base64.b64encode(
                        b"GARMIN_CONNECT_MOBILE_ANDROID_DI_2025Q2:",
                    ).decode(),
                    "Accept": "application/json,*/*;q=0.8",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "GCM-Android-5.23",
                },
                data={
                    "client_id": "GARMIN_CONNECT_MOBILE_ANDROID_DI_2025Q2",
                    "service_ticket": "ST-0-probe-host-reachability",
                    "grant_type": (
                        "https://connectapi.garmin.com/di-oauth2-service/"
                        "oauth/grant/service_ticket"
                    ),
                    "service_url": "https://connect.garmin.cn/app",
                },
                timeout=20,
            )
            print(f"  POST status: {resp.status_code}")
            print(f"  body: {_snippet(resp)}")
        except Exception as e:
            print(f"  POST EXC {type(e).__name__}: {e}")

    return 0


# --------------------------------------------------------------------------- #
#  Mode: grants — sweep grant_type values against diauth.garmin.cn            #
# --------------------------------------------------------------------------- #

_CN_DIAUTH_URL = "https://diauth.garmin.cn/di-oauth2-service/oauth/token"  # noqa: S105

_GRANT_CANDIDATES = [
    # The library's current value (points at .com) — works verbatim on CN
    "https://connectapi.garmin.com/di-oauth2-service/oauth/grant/service_ticket",
    "https://connectapi.garmin.cn/di-oauth2-service/oauth/grant/service_ticket",
    "service_ticket",
    "authorization_code",
    "client_credentials",
    "password",
    "refresh_token",
    "urn:ietf:params:oauth:grant-type:service-ticket",
    "urn:garmin:grant-type:service_ticket",
]

_CLIENT_IDS = [
    "GARMIN_CONNECT_MOBILE_ANDROID_DI_2025Q2",
    "GARMIN_CONNECT_MOBILE_ANDROID_DI_2024Q4",
    "GARMIN_CONNECT_MOBILE_ANDROID_DI",
    "GARMIN_CONNECT_MOBILE_IOS_DI",
]


def _mode_grants(args: argparse.Namespace) -> int:
    try:
        from curl_cffi import requests as cffi_requests

        sess: Any = cffi_requests.Session(impersonate="chrome")
    except ImportError:
        import requests

        sess = requests.Session()

    def _probe(grant_type: str, client_id: str) -> str:
        auth = "Basic " + base64.b64encode(f"{client_id}:".encode()).decode()
        try:
            r = sess.request(
                "POST", _CN_DIAUTH_URL,
                headers={
                    "Authorization": auth,
                    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "GCM-Android-5.23",
                },
                data={
                    "client_id": client_id,
                    "service_ticket": "ST-0-grant-probe",
                    "grant_type": grant_type,
                    "service_url": "https://connect.garmin.cn/app",
                },
                timeout=20,
            )
            return f"{r.status_code} {_snippet(r)}"
        except Exception as e:
            return f"EXC {type(e).__name__}: {str(e)[:120]}"

    print(f"POST {_CN_DIAUTH_URL}\n")
    header = f"{'grant_type':75}  {'client_id':45}  status/body"
    print(header)
    print("-" * len(header))

    primary_cid = _CLIENT_IDS[0]
    for gt in _GRANT_CANDIDATES:
        print(f"{gt[:75]:75}  {primary_cid[:45]:45}  {_probe(gt, primary_cid)[:250]}")

    print("\n--- sweep client_id with the CN-flavoured grant_type ---")
    cn_grant = _GRANT_CANDIDATES[1]
    for cid in _CLIENT_IDS:
        print(f"{cn_grant[:75]:75}  {cid[:45]:45}  {_probe(cn_grant, cid)[:250]}")

    print("\nInterpreting results:")
    print("  'invalid service ticket provided' -> grant_type recognised "
          "(this is the target)")
    print("  'unsupported_grant_type'          -> not a valid grant_type")
    print("  'Unauthorized' / Whitelabel Error -> client_id not recognised")
    return 0


# --------------------------------------------------------------------------- #
#  CLI                                                                        #
# --------------------------------------------------------------------------- #

def _run_all(args: argparse.Namespace) -> int:
    for mode_fn in (_mode_login, _mode_api, _mode_grants):
        print("\n" + "#" * 72)
        print(f"#  {mode_fn.__name__}")
        print("#" * 72)
        rc = mode_fn(args)
        if rc:
            return rc
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Garmin Connect diagnostic toolkit. "
                    "See module docstring for details.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    p_login = sub.add_parser(
        "login", help="Probe the five-strategy login chain",
    )
    p_login.add_argument(
        "--default-only", action="store_true",
        help="Skip individual strategies; only run Client.login()",
    )
    p_login.set_defaults(func=_mode_login)

    p_api = sub.add_parser(
        "api",
        help="Probe connectapi + connect/proxy endpoints after login",
    )
    p_api.add_argument(
        "--probe-diauth-cn", action="store_true",
        help="Also ping diauth.garmin.cn reachability "
             "(implicit when GARMIN_IS_CN=true)",
    )
    p_api.set_defaults(func=_mode_api)

    p_grants = sub.add_parser(
        "grants",
        help="Sweep grant_type values vs diauth.garmin.cn (no creds)",
    )
    p_grants.set_defaults(func=_mode_grants)

    p_all = sub.add_parser(
        "all", help="Run login + api + grants in sequence",
    )
    # ``all`` needs to accept flags from both login and api sub-parsers.
    p_all.add_argument("--default-only", action="store_true")
    p_all.add_argument("--probe-diauth-cn", action="store_true")
    p_all.set_defaults(func=_run_all)

    args = parser.parse_args()
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
