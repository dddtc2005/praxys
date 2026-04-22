"""One-shot diagnostic: dump what Garmin actually returns for the connected
user's profile, heart rates, and today's sleep/HRV payloads.

Run from the project root after a successful sync:
    .venv\\Scripts\\python.exe scripts\\garmin_profile_probe.py

Prints the top-level keys of each payload and highlights any field whose
name contains "heart", "hr", "rest", "max", or "sleep". Use the output to
decide which key names `parse_user_profile` and `parse_garmin_recovery`
should be reading.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date

sys.path.insert(0, os.getcwd())
from dotenv import load_dotenv

load_dotenv(".env")
if not os.environ.get("PRAXYS_LOCAL_ENCRYPTION_KEY"):
    print("ERROR: PRAXYS_LOCAL_ENCRYPTION_KEY not in .env (run from project root)")
    sys.exit(1)

from db import session as s

s.init_db()
db = s.SessionLocal()
from db.crypto import get_vault
from db.models import UserConnection

USER_ID = "50b59a9a-c3a2-4b35-8303-e5211bc3d632"
conn = (
    db.query(UserConnection)
    .filter(UserConnection.user_id == USER_ID, UserConnection.platform == "garmin")
    .first()
)
if not conn:
    print("No Garmin connection")
    sys.exit(0)

vault = get_vault()
creds = json.loads(vault.decrypt(conn.encrypted_credentials, conn.wrapped_dek))

from garminconnect import Garmin

client = Garmin(creds["email"], creds["password"], is_cn=creds.get("is_cn", False))
token_dir = os.path.join("sync", ".garmin_tokens", USER_ID)
has_tokens = all(
    os.path.isfile(os.path.join(token_dir, n))
    for n in ("oauth1_token.json", "oauth2_token.json")
)
client.login(token_dir if has_tokens else None)


def _flatten_keys(obj, prefix=""):
    """Yield (path, value-type, sample) for every leaf."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                yield from _flatten_keys(v, p)
            else:
                yield (p, type(v).__name__, repr(v)[:60])
    elif isinstance(obj, list) and obj:
        yield from _flatten_keys(obj[0], prefix + "[0]")


def _highlight(key: str) -> bool:
    k = key.lower()
    return any(tag in k for tag in ("heart", "hr", "rest", "max", "sleep", "rmssd"))


def dump(label, payload, show_all=False):
    print(f"\n===== {label} =====")
    if payload is None:
        print("  <None>")
        return
    if not isinstance(payload, (dict, list)):
        print(f"  {type(payload).__name__}: {payload!r}"[:120])
        return
    hits = []
    for path, typ, sample in _flatten_keys(payload):
        if show_all or _highlight(path):
            hits.append(f"  {path}: ({typ}) {sample}")
    if hits:
        print("\n".join(hits))
    else:
        print("  (no HR/sleep/rest fields found)")


today = date.today().isoformat()

try:
    profile = client.get_user_profile()
    dump("get_user_profile() — HR/rest fields", profile)
except Exception as e:
    print(f"get_user_profile failed: {e}")

try:
    hr = client.get_heart_rates(today)
    dump(f"get_heart_rates({today}) — HR fields", hr)
except Exception as e:
    print(f"get_heart_rates failed: {e}")

try:
    sleep = client.get_sleep_data(today)
    dump(f"get_sleep_data({today}) — sleep/HR fields", sleep)
except Exception as e:
    print(f"get_sleep_data failed: {e}")

try:
    from datetime import timedelta

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    sleep_y = client.get_sleep_data(yesterday)
    dump(f"get_sleep_data({yesterday}) — sleep/HR fields", sleep_y)
except Exception as e:
    print(f"get_sleep_data yesterday failed: {e}")

# --- Hunt for Garmin's running Critical Power / Threshold Power ---
# Known cycling is via get_cycling_ftp. Running CP isn't a first-class
# method; probe the profile (all keys), max_metrics, personal records,
# userprofile_settings, and the training-status payload.


def dump_all(label, payload):
    """Dump EVERY leaf key — not just HR-filtered — so we can spot the
    running-power / critical-power fields."""
    print(f"\n===== {label} (full) =====")
    if payload is None:
        print("  <None>")
        return
    shown = 0
    for path, typ, sample in _flatten_keys(payload):
        k = path.lower()
        if any(tag in k for tag in (
            "power", "ftp", "critical", "threshold", "vo2", "running",
        )):
            print(f"  {path}: ({typ}) {sample}")
            shown += 1
    if shown == 0:
        print("  (no power/ftp/critical/threshold/vo2/running keys found)")


try:
    max_m = client.get_max_metrics(today)
    dump_all("get_max_metrics(today)", max_m)
except Exception as e:
    print(f"get_max_metrics failed: {e}")

try:
    pr = client.get_personal_record()
    dump_all("get_personal_record()", pr)
except Exception as e:
    print(f"get_personal_record failed: {e}")

try:
    settings = client.get_userprofile_settings()
    dump_all("get_userprofile_settings()", settings)
except Exception as e:
    print(f"get_userprofile_settings failed: {e}")

try:
    ts = client.get_training_status(today)
    dump_all("get_training_status(today)", ts)
except Exception as e:
    print(f"get_training_status failed: {e}")

try:
    cycling_ftp = client.get_cycling_ftp()
    print(f"\n===== get_cycling_ftp() =====")
    print(f"  {cycling_ftp!r}")
except Exception as e:
    print(f"get_cycling_ftp failed: {e}")

# Candidate raw endpoints for running CP / threshold power. Garmin doesn't
# wrap this in garminconnect but the web /modern/report/-39/running/current
# report page clearly fetches it from somewhere.
candidates = [
    "/biometric-service/biometric/threshold/runningPower",
    "/biometric-service/biometric/threshold/running_power",
    "/biometric-service/biometric/criticalPower/running",
    "/biometric-service/biometric/ftp/running",
    "/biometric-service/biometric/runningPower",
    "/biometric-service/biometric/running/threshold/power",
    "/biometric-service/stats/threshold/running/power",
    "/biometric-service/stats/running/threshold/power",
    "/userprofile-service/userprofile/power/running",
    "/userprofile-service/userprofile/runningPower",
    # The -39 report endpoint
    "/userreportbuilder-service/reportbuilder/report/-39/running/current",
    "/reportbuilder-service/reportbuilder/report/-39/running/current",
    "/userreportbuilder-service/report/-39/running/current",
    "/fitnessstats-service/activity/threshold",
]
print("\n===== Raw endpoint probe - running CP/FTP =====")
for path in candidates:
    try:
        resp = client.connectapi(path)
        if resp:
            print(f"  OK {path}: {type(resp).__name__}")
            if isinstance(resp, dict):
                for k, v in list(resp.items())[:10]:
                    print(f"      {k}: {v!r}"[:100])
            elif isinstance(resp, list):
                print(f"      list len={len(resp)}, first: {resp[0] if resp else None}")
            else:
                print(f"      {resp!r}"[:200])
        else:
            print(f"  -- {path}: empty")
    except Exception as e:
        msg = str(e)[:80]
        print(f"  NO {path}: {msg}")
