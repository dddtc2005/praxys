r"""One-shot Garmin MFA token-acceptance probe (praxys #378 / upstream garminconnect #369).

Mirrors the app's real login flow (Garmin(return_on_mfa=True) -> resume_login)
but FORCES one login strategy via skip_strategies. Goal: for an MFA-enabled
account, confirm the `portal` strategy mints a DI token the Garmin API tier
ACCEPTS -- unlike the `widget` strategy (the MFA path today), whose token
/userprofile-service/socialProfile rejects with 401 (upstream #369).

Forcing portal sends exactly ONE MFA code. Enter the code that arrives RIGHT
AFTER the 'needs_mfa' line -- ignore any older codes from earlier attempts,
and enter it promptly (codes expire).

    $env:GARMIN_EMAIL="you@example.com"
    $env:GARMIN_PASSWORD="..."
    # $env:GARMIN_IS_CN="true"     # for garmin.cn accounts
    .venv\Scripts\python.exe scripts\garmin_mfa_probe.py --strategy portal

Options: --strategy {portal,widget,default}  (default: portal = candidate fix)

Prints only hostnames, status codes and booleans -- no credentials/tokens/PII.
"""
from __future__ import annotations

import argparse
import os
import sys
import time as _time


def _creds() -> tuple[str, str, bool]:
    email = os.environ.get("GARMIN_EMAIL") or os.environ.get("GARMIN_CN_EMAIL")
    password = os.environ.get("GARMIN_PASSWORD") or os.environ.get("GARMIN_CN_PASSWORD")
    if not email or not password:
        sys.exit("Set GARMIN_EMAIL and GARMIN_PASSWORD env vars first.")
    is_cn = os.environ.get("GARMIN_IS_CN", "").strip().lower() in ("1", "true", "yes", "y")
    return email, password, is_cn


SKIP = {
    "portal": {"mobile+cffi", "mobile+requests", "widget+cffi"},
    "widget": {"mobile+cffi", "mobile+requests", "portal+cffi", "portal+requests"},
    "default": set(),
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Probe Garmin login-strategy token acceptance for MFA accounts.")
    ap.add_argument("--strategy", choices=["portal", "widget", "default"], default="portal")
    args = ap.parse_args()

    email, password, is_cn = _creds()

    from garminconnect import Garmin

    g = Garmin(email, password, is_cn=is_cn, return_on_mfa=True)
    g.client.skip_strategies = set(SKIP[args.strategy])
    print(f"# is_cn={is_cn}  forcing strategy={args.strategy}  (skipping: {sorted(g.client.skip_strategies) or 'none'})")
    print("# note: portal login has a built-in ~10-20s anti-WAF delay before the code is sent.")

    try:
        status, _ = g.login()
    except Exception as e:
        print(f"# login() raised: {type(e).__name__}: {str(e)[:400]}")
        return 2

    if status == "needs_mfa":
        print(f"# needs_mfa at {_time.strftime('%H:%M:%S')} via flow={getattr(g.client, '_mfa_flow', '?')}")
        print("# --> enter the code that arrives RIGHT NOW (ignore older codes)")
        code = input("Enter MFA code: ").strip()
        try:
            g.resume_login({}, code)
        except Exception as e:
            print(f"# resume_login FAILED: {type(e).__name__}: {str(e)[:500]}")
            return 2
        print("# MFA completed.")
    else:
        print(f"# login returned status={status!r} (no MFA challenge on this path)")

    print(f"# di_token present: {bool(getattr(g.client, 'di_token', None))}")

    ok = True
    for path in (
        "/userprofile-service/socialProfile",
        "/userprofile-service/userprofile/user-settings",
    ):
        try:
            resp = g.client.connectapi(path)
            has = isinstance(resp, dict) and len(resp) > 0
            print(f"#   GET {path} -> 200 (payload: {'yes' if has else 'empty'})")
        except Exception as e:
            ok = False
            print(f"#   GET {path} -> FAIL: {type(e).__name__}: {str(e)[:200]}")

    print()
    if ok:
        print(f"RESULT: '{args.strategy}' strategy token ACCEPTED by API tier  -> WORKS for MFA sync")
    else:
        print(f"RESULT: '{args.strategy}' strategy token REJECTED by API tier  -> matches upstream #369")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
