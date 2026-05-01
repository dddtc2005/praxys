"""Data sync endpoints — per-user sync with encrypted credentials.

Credentials are read from user_connections (encrypted in DB). Falls back to
environment variables when auth is disabled (local dev).
"""
import json
import logging
import os
import threading
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from api.auth import get_data_user_id, require_write_access
from api.env_compat import getenv_compat
from api.views import utc_isoformat
from db.session import get_db

router = APIRouter()


class SyncRequest(BaseModel):
    """Optional request body for sync endpoints."""
    from_date: str | None = None

    @field_validator("from_date")
    @classmethod
    def validate_date_format(cls, v: str | None) -> str | None:
        if v is not None:
            from datetime import datetime as dt
            try:
                dt.strptime(v, "%Y-%m-%d")
            except ValueError:
                raise ValueError("from_date must be in YYYY-MM-DD format")
        return v


# Per-user sync status: {user_id: {source: {status, last_sync, error}}}
_sync_status: dict[str, dict[str, dict]] = {}
_sync_lock = threading.Lock()

_DEFAULT_SOURCES = ["garmin", "strava", "stryd", "oura", "coros"]


def _get_user_status(user_id: str) -> dict[str, dict]:
    """Get or create sync status dict for a user."""
    with _sync_lock:
        if user_id not in _sync_status:
            _sync_status[user_id] = {
                s: {"status": "idle", "last_sync": None, "error": None}
                for s in _DEFAULT_SOURCES
            }
        return _sync_status[user_id]


def _get_data_dir() -> str:
    return os.environ.get(
        "DATA_DIR",
        os.path.join(os.path.dirname(__file__), "..", "..", "data"),
    )


def _garmin_token_root() -> str:
    """Root directory that holds per-user Garmin token sub-directories."""
    return os.path.join(
        os.path.dirname(_get_data_dir()), "sync", ".garmin_tokens",
    )


def _garmin_token_dir(user_id: str) -> str:
    """Per-user Garmin tokenstore path.

    garminconnect.Garmin.login() loads any tokens it finds at this path from
    disk without validating whose Garmin account they belong to, so a shared
    directory would leak one user's authenticated session to the next caller.
    """
    return os.path.join(_garmin_token_root(), user_id)


def clear_garmin_tokens(user_id: str) -> None:
    """Remove cached Garmin OAuth tokens for a user.

    Call whenever cached tokens should no longer be trusted: credential
    rotation on connect, explicit disconnect, or user deletion. Leaves the
    token root intact. Raises OSError on filesystem failure — callers decide
    whether that's fatal (connect flow) or best-effort (post-delete cleanup).
    Silencing failures here would re-open the cross-user leak the helper exists
    to prevent.
    """
    import shutil
    path = _garmin_token_dir(user_id)
    if not os.path.isdir(path):
        return
    try:
        shutil.rmtree(path)
    except OSError:
        logger.exception(
            "Failed to clear Garmin tokenstore for user %s at %s — "
            "stale tokens may still be reused on next sync.",
            user_id, path,
        )
        raise


def _get_credentials(user_id: str, platform: str, db: Session) -> dict | None:
    """Get decrypted credentials for a user's platform connection.

    Returns credential dict or None if not connected. Falls back to env vars
    when auth is disabled (dev mode).
    """
    from db.models import UserConnection

    conn = db.query(UserConnection).filter(
        UserConnection.user_id == user_id,
        UserConnection.platform == platform,
    ).first()

    if conn and conn.encrypted_credentials and conn.wrapped_dek:
        from db.crypto import get_vault
        vault = get_vault()
        try:
            creds_json = vault.decrypt(conn.encrypted_credentials, conn.wrapped_dek)
            return json.loads(creds_json)
        except Exception as e:
            logger.warning("Failed to decrypt credentials for %s/%s: %s",
                           user_id, platform, e)

    return None


def _persist_credentials(user_id: str, platform: str, creds: dict, db: Session) -> None:
    """Encrypt and persist updated platform credentials."""

    from db.crypto import get_vault
    from db.models import UserConnection

    vault = get_vault()
    encrypted_credentials, wrapped_dek = vault.encrypt(json.dumps(creds))
    conn = db.query(UserConnection).filter(
        UserConnection.user_id == user_id,
        UserConnection.platform == platform,
    ).first()
    if conn is None:
        return
    conn.encrypted_credentials = encrypted_credentials
    conn.wrapped_dek = wrapped_dek


def _get_strava_client_config() -> tuple[str, str]:
    """Load Strava OAuth client credentials from environment."""

    client_id = getenv_compat("STRAVA_CLIENT_ID")
    client_secret = getenv_compat("STRAVA_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "Strava OAuth is not configured. Set PRAXYS_STRAVA_CLIENT_ID and PRAXYS_STRAVA_CLIENT_SECRET."
        )
    return client_id, client_secret


def _run_sync(user_id: str, source: str, creds: dict,
              from_date: str | None = None) -> None:
    """Run sync for a single source. Called in a background thread.

    Fetches data from platform APIs and writes directly to DB — no CSV
    intermediate step. The sync scripts' parse functions produce row dicts
    which are written to DB via db.sync_writer.

    Args:
        user_id: User to sync for.
        source: Platform name (garmin, stryd, oura).
        creds: Decrypted credentials dict.
        from_date: Optional start date for backfill.
    """
    from db.session import init_db, SessionLocal
    from db.models import UserConnection
    from db import sync_writer

    status = _get_user_status(user_id)

    with _sync_lock:
        status[source] = {"status": "syncing", "last_sync": None, "error": None}

    init_db()
    db = SessionLocal()

    try:
        counts = {}

        if source == "garmin":
            counts = _sync_garmin(user_id, creds, from_date, db)

        elif source == "strava":
            counts = _sync_strava(user_id, creds, from_date, db)

        elif source == "stryd":
            counts = _sync_stryd(user_id, creds, from_date, db)

        elif source == "oura":
            counts = _sync_oura(user_id, creds, from_date, db)

        elif source == "coros":
            counts = _sync_coros(user_id, creds, from_date, db)

        else:
            raise ValueError(f"Unknown source: {source}")

        db.commit()

        # Refresh activity-derived CP on any sync that can change activity
        # power observations (Garmin, Strava, Stryd — not Oura). The fit
        # itself is cheap and idempotent; skipping Oura just avoids the
        # no-op DB read.
        if source in ("garmin", "strava", "stryd", "coros"):
            try:
                from db.sync_writer import update_cp_from_activities
                fit = update_cp_from_activities(user_id, db)
                if fit is not None:
                    db.commit()
                    logger.info(
                        "Activity-derived CP for user %s: %.1fW (r²=%.2f, %d points)",
                        user_id, fit["cp_watts"], fit["r_squared"], fit["point_count"],
                    )
            except Exception:
                # CP refresh is best-effort; never let it break the sync.
                logger.exception("Activity-derived CP refresh failed for user %s", user_id)
                db.rollback()

        # Update last_sync on the connection record
        conn = db.query(UserConnection).filter(
            UserConnection.user_id == user_id,
            UserConnection.platform == source,
        ).first()
        if conn:
            conn.last_sync = datetime.now(timezone.utc).replace(tzinfo=None)
            conn.status = "connected"
            db.commit()

        logger.info("Sync %s for user %s: %s", source, user_id, counts)

        # Post-sync LLM insight generation. Best-effort: failures here must
        # never break the sync. The runner is content-addressable (skips when
        # the dataset hash is unchanged) and self-throttling (per-user daily
        # cap), so calling it on every sync is safe.
        try:
            from api.insights_runner import run_insights_for_user
            insight_results = run_insights_for_user(user_id, db, counts)
            logger.info("Insight generation for user %s: %s", user_id, insight_results)
        except Exception:
            # No rollback: the runner uses its own session, and the caller's
            # session has nothing pending past the prior db.commit().
            logger.exception("Insight generation failed for user %s", user_id)

        with _sync_lock:
            status[source] = {
                "status": "done",
                "last_sync": utc_isoformat(datetime.now(timezone.utc)),
                "error": None,
            }

    except Exception as e:
        db.rollback()
        logger.exception("Sync failed for %s (user %s)", source, user_id)
        with _sync_lock:
            status[source] = {
                "status": "error",
                "last_sync": None,
                "error": str(e),
            }
        # Update connection status to error
        try:
            conn = db.query(UserConnection).filter(
                UserConnection.user_id == user_id,
                UserConnection.platform == source,
            ).first()
            if conn:
                conn.status = "error"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


_CN_DI_TOKEN_URL = "https://diauth.garmin.cn/di-oauth2-service/oauth/token"  # noqa: S105

# Serializes any in-flight DI_TOKEN_URL rebind. Concurrent international
# logins in the same process would otherwise race on the module-level
# constant — see _patch_cn_di_exchange's docstring.
_di_token_url_lock = threading.Lock()


def _patch_cn_di_exchange(inner_client) -> None:
    """Re-target DI Bearer token exchange to ``diauth.garmin.cn``.

    ``garminconnect`` 0.3.x hardcodes ``DI_TOKEN_URL`` at
    ``diauth.garmin.com``. Garmin's CN infrastructure has a parallel
    service at ``diauth.garmin.cn`` that accepts the same client IDs and
    the same (``.com``-shaped) ``grant_type`` identifier — verified via
    ``scripts/garmin_diagnose.py grants``. Pointing the exchange at the
    CN host is enough to make it issue real DI tokens for CN accounts;
    after that, ``connectapi.garmin.cn`` accepts Bearer auth normally.

    The method *bindings* are instance-scoped (``types.MethodType`` on
    this ``Client`` only). The library resolves ``DI_TOKEN_URL`` from its
    module globals at call time, so the override has to transiently
    rebind the module constant during the call and restore it in
    ``finally``. That window IS process-global, so we serialize all CN
    swaps with ``_di_token_url_lock`` — a concurrent international login
    whose own exchange call overlaps the window would otherwise read the
    CN URL and fail.

    Both exchange sites need the patch:
    * ``_exchange_service_ticket`` — called during initial login, after
      a CAS service ticket is issued.
    * ``_refresh_di_token`` — called by ``_refresh_session`` when a
      persisted DI token is close to expiry. Without this, a long backfill
      that crosses the token TTL would refresh against ``.com``, fail, and
      silently stall on 401 cascades.

    Coupled to garminconnect 0.3.x internals (``DI_TOKEN_URL`` module name,
    ``_exchange_service_ticket`` / ``_refresh_di_token`` method names).
    Re-validate with ``scripts/garmin_diagnose.py grants`` after any
    upstream bump — none of these symbols are part of the library's
    public contract.
    """
    import types
    from garminconnect import client as _gc_client

    orig_exchange = inner_client._exchange_service_ticket
    orig_refresh = inner_client._refresh_di_token

    def _cn_exchange(self, ticket, service_url=None):
        with _di_token_url_lock:
            prev = _gc_client.DI_TOKEN_URL
            _gc_client.DI_TOKEN_URL = _CN_DI_TOKEN_URL
            try:
                return orig_exchange.__func__(
                    self, ticket, service_url=service_url,
                )
            finally:
                _gc_client.DI_TOKEN_URL = prev

    def _cn_refresh(self):
        with _di_token_url_lock:
            prev = _gc_client.DI_TOKEN_URL
            _gc_client.DI_TOKEN_URL = _CN_DI_TOKEN_URL
            try:
                return orig_refresh.__func__(self)
            finally:
                _gc_client.DI_TOKEN_URL = prev

    inner_client._exchange_service_ticket = types.MethodType(
        _cn_exchange, inner_client,
    )
    inner_client._refresh_di_token = types.MethodType(
        _cn_refresh, inner_client,
    )


def _login_garmin_with_cn_fallback(client, creds: dict, token_dir: str) -> None:
    """Log in the Garmin client, handling the 0.3.x library's CN blind spots.

    Two upstream problems overlap here:

    1. **DI Bearer exchange target is ``.com`` only.** The module-level
       ``DI_TOKEN_URL`` points at ``diauth.garmin.com``, which has no
       record of CN accounts (always 400/401). Without a DI token,
       ``connectapi.garmin.cn`` rejects every API call with 403 — JWT_WEB
       cookie auth isn't accepted on the API gateway. Pointing the
       exchange at ``diauth.garmin.cn`` produces real Bearer tokens that
       authenticate both regions. See ``_patch_cn_di_exchange``.

    2. **Mobile/widget strategies' JWT_WEB fallback is ``.com``-only.**
       The first four login strategies can reach a point where the CAS
       ticket is consumed against ``mobile.integration.garmin.com`` /
       ``sso.garmin.com/sso/embed`` — for CN the DNS fails or no
       ``JWT_WEB`` cookie is set. The library re-raises that as an auth
       error and aborts the chain *before* reaching the portal strategies
       (which do use the domain-aware ``_portal_service_url``). When we
       see that specific message we retry ``_portal_web_login_cffi``
       directly. The message match keeps real credential failures
       (``"Invalid Username or Password"``) bubbling up.
    """
    import contextlib
    from garminconnect.exceptions import GarminConnectAuthenticationError

    if getattr(client, "is_cn", False):
        _patch_cn_di_exchange(client.client)

    try:
        client.login(token_dir)
        return
    except GarminConnectAuthenticationError as e:
        if "JWT_WEB cookie not set" not in str(e):
            raise
        logger.warning(
            "Garmin login hit JWT_WEB fallback bug (hardcoded .com host); "
            "retrying via portal strategy.",
        )

    inner = client.client
    inner._portal_web_login_cffi(creds["email"], creds["password"])
    # With the CN DI patch in place this now produces real Bearer tokens
    # for CN accounts; ``Client.dump`` serializes only DI state, so this
    # persistence attempt is meaningful for both regions.
    with contextlib.suppress(Exception):
        inner.dump(token_dir)


def _sync_garmin(user_id: str, creds: dict, from_date: str | None,
                 db) -> dict:
    """Fetch Garmin data and write directly to DB."""
    from db import sync_writer
    from garminconnect import Garmin
    from sync.garmin_sync import (
        parse_activities, parse_splits, parse_daily_metrics,
        parse_lactate_threshold, parse_user_profile, parse_heart_rates,
        parse_running_ftp, RATE_LIMIT_DELAY,
    )
    import time

    # Region resolution: the Settings UI writes user_config.source_options.
    # garmin_region, but the reconnect flow separately stores is_cn inside the
    # encrypted credentials blob. These two values used to drift — a user
    # could change the region in Settings, see it reflected in the UI, and
    # still hit the wrong Garmin SSO because the sync read is_cn only from
    # the encrypted blob. Prefer source_options as the authoritative setting;
    # fall back to the legacy creds.is_cn for connections that predate the
    # region toggle.
    from analysis.config import load_config_from_db
    user_config = load_config_from_db(user_id, db)
    region = user_config.source_options.get("garmin_region")
    if region in ("cn", "international"):
        is_cn = region == "cn"
    else:
        is_cn = bool(creds.get("is_cn", False))

    client = Garmin(creds["email"], creds["password"], is_cn=is_cn)
    # The tokenstore must be per-user: garminconnect.Garmin.login() loads any
    # tokens at that path without validating the account they belong to and
    # only falls back to username/password if the files themselves are missing
    # or malformed. A shared path would have every user's sync fetching the
    # first-authenticated user's Garmin data.
    token_dir = _garmin_token_dir(user_id)
    os.makedirs(token_dir, exist_ok=True)
    # Garmin.login(path) transparently handles a missing tokenstore: load()
    # raises, the exception is caught internally, and the credentials flow
    # runs. On success it writes garmin_tokens.json back to the same path.
    _login_garmin_with_cn_fallback(client, creds, token_dir)

    end = date.today().isoformat()
    start = from_date or (date.today() - timedelta(days=7)).isoformat()

    # Read configured activity categories from user config (already loaded
    # above for region resolution). Garmin's search API only accepts top-level
    # types (running, cycling, etc.) not subtypes (trail_running,
    # treadmill_running). We fetch by top-level category — all subtypes are
    # returned automatically.
    categories = user_config.source_options.get(
        "garmin_activity_categories", ["running"]
    )
    # Map category names to Garmin API activitytype parameter
    CATEGORY_TO_API_TYPE = {
        "running": "running",
        "cycling": "cycling",
        "swimming": "swimming",
        "hiking": "hiking",
        "walking": "walking",
        # "strength" intentionally absent: Garmin's API now rejects
        # activityType=strength_training with "Activity type cannot be an
        # activity sub type" (it was reclassified as a subtype of
        # fitness_equipment). Users who selected Strength in Setup will
        # have it fall through to the top-level query via the default
        # mapping (``c`` maps to itself). The resulting 400 is logged at
        # warning level and the other categories still sync fine.
    }
    api_types = list({CATEGORY_TO_API_TYPE.get(c) for c in categories if CATEGORY_TO_API_TYPE.get(c)})

    # Fetch activities for each configured type
    raw_activities = []
    for atype in api_types:
        try:
            batch = client.get_activities_by_date(start, end, activitytype=atype)
            raw_activities.extend(batch)
        except Exception as e:
            logger.warning(
                "Garmin activities fetch failed for user %s type %s: %s",
                user_id, atype, e,
            )
    activity_rows = parse_activities(raw_activities)
    act_count = sync_writer.write_activities(user_id, activity_rows, db)

    # Splits — per-activity lap data. Splits drive interval intensity analysis
    # (see CLAUDE.md: "Always use activity_splits.csv for intensity analysis").
    # Per-activity misses are logged at debug, but a systemic failure would
    # quietly lose intensity metrics, so we surface an aggregate warning.
    status = _get_user_status(user_id)
    activity_ids = [str(a.get("activityId", "")) for a in raw_activities]
    total = len(activity_ids)
    all_splits = []
    split_failures = 0
    for idx, aid in enumerate(activity_ids):
        with _sync_lock:
            status["garmin"]["progress"] = f"Fetching splits: {idx + 1}/{total}"
        try:
            splits_data = client.get_activity_splits(aid) or {}
            all_splits.extend(parse_splits(aid, splits_data))
            time.sleep(RATE_LIMIT_DELAY)
        except Exception as e:
            split_failures += 1
            logger.debug("Splits for %s: skipped (%s)", aid, e)
    if total and split_failures >= max(3, total // 2):
        logger.warning(
            "Garmin splits fetch failed for %d of %d activities (user %s) — "
            "intensity analysis will be missing for those runs",
            split_failures, total, user_id,
        )
    split_count = sync_writer.write_splits(user_id, all_splits, db)

    # Lactate threshold. Log at warning so intermittent failures surface
    # instead of vanishing at debug level — the previous behaviour silently
    # hid real failures when endpoints rejected the request.
    lt_count = 0
    try:
        lt_start = (date.today() - timedelta(days=365)).isoformat()
        lt_data = client.get_lactate_threshold(latest=False, start_date=lt_start, end_date=end)
        lt_rows = parse_lactate_threshold(lt_data)
        if not lt_rows:
            lt_rows = parse_lactate_threshold(client.get_lactate_threshold(latest=True))
        lt_count = sync_writer.write_lactate_threshold(user_id, lt_rows, db)
    except Exception as e:
        logger.warning("Garmin lactate threshold fetch failed for user %s: %s", user_id, e)

    # User profile + today's heart-rates → threshold inputs for _resolve_thresholds.
    # Profile carries LTHR (and sometimes max HR). The profile endpoint does
    # NOT return resting HR on International accounts — that comes from
    # get_heart_rates(date), whose lastSevenDaysAvgRestingHeartRate is the
    # stable reference we want for TRIMP's rest_hr.
    profile_count = 0
    try:
        profile_raw = client.get_user_profile()
        profile_parsed = parse_user_profile(profile_raw)
    except Exception as e:
        profile_parsed = {}
        logger.warning("Garmin user profile fetch failed for user %s: %s", user_id, e)

    today_str = date.today().isoformat()
    try:
        today_hr = client.get_heart_rates(today_str) or {}
        hr_parsed = parse_heart_rates(today_hr)
        rolling = hr_parsed.get("rolling_rest_hr")
        if rolling is not None:
            profile_parsed["rest_hr_bpm"] = rolling
    except Exception as e:
        logger.warning("Garmin heart_rates fetch failed for user %s: %s", user_id, e)

    # Running FTP / Critical Power. Garmin exposes this at the same URL
    # pattern as cycling FTP — garminconnect wraps cycling but not running,
    # so we call the endpoint directly. Note: Garmin's native running power
    # reads substantially higher than Stryd (~30% gap on the same athlete);
    # see docs/dev/gotchas.md. For users who have both sources syncing, the
    # latest write to fitness_data.cp_estimate wins — which can cause CP
    # thresholds to whiplash between the two systems.
    try:
        rftp_raw = client.connectapi(
            "/biometric-service/biometric/latestFunctionalThresholdPower/RUNNING"
        )
        rftp_parsed = parse_running_ftp(rftp_raw)
        if rftp_parsed:
            profile_parsed.update(rftp_parsed)
    except Exception as e:
        logger.warning("Garmin running FTP fetch failed for user %s: %s", user_id, e)

    if profile_parsed:
        try:
            profile_count = sync_writer.write_profile_thresholds(
                user_id, profile_parsed, db,
            )
        except Exception as e:
            logger.warning(
                "Garmin profile threshold write failed for user %s: %s", user_id, e,
            )

    # Daily metrics (VO2max, training status, readiness, race prediction).
    # Kept independent of recovery so one endpoint failing (common on Garmin
    # CN where some endpoints aren't live) doesn't wipe out the other.
    dm_count = 0
    tr = None
    try:
        today_str = date.today().isoformat()
        ts = client.get_training_status(today_str) or {}
        try:
            tr = client.get_training_readiness(today_str)
        except Exception as e:
            logger.debug("Training readiness: skipped (%s)", e)
        rp = None
        try:
            rp = client.get_race_predictions()
        except Exception as e:
            logger.debug("Race predictions: skipped (%s)", e)
        dm_rows = parse_daily_metrics(today_str, ts, training_readiness=tr, race_predictions=rp)
        dm_count = sync_writer.write_daily_metrics(user_id, dm_rows, db)
    except Exception as e:
        logger.warning("Garmin daily metrics fetch failed for user %s: %s", user_id, e)

    # Recovery (HRV, sleep, readiness). Honour the same date window as the
    # activity sync so a 6-month backfill doesn't leave us with a 7-day HRV
    # trend. Cap to a year to avoid hammering Garmin if from_date is ancient.
    recovery_count = 0
    recovery_rows: list[dict] = []
    try:
        from sync.garmin_sync import parse_garmin_recovery

        start_date = date.fromisoformat(start)
        today_date = date.today()
        requested_days = (today_date - start_date).days + 1
        total_days = max(1, min(requested_days, 365))
        if requested_days > total_days:
            logger.info(
                "Garmin recovery backfill window capped at %d days for user %s "
                "(requested %d)", total_days, user_id, requested_days,
            )

        # Circuit-breaker: if an endpoint rejects N consecutive times, stop
        # calling it for the rest of the loop. Prevents a 180-day backfill
        # with a systemic auth failure from spamming 360 debug lines and
        # waiting RATE_LIMIT_DELAY×180 for nothing.
        consec_break = 5
        hrv_fail_streak = 0
        sleep_fail_streak = 0
        hr_fail_streak = 0
        hrv_last_err: Exception | None = None
        sleep_last_err: Exception | None = None
        hr_last_err: Exception | None = None
        hrv_aborted = False
        sleep_aborted = False
        hr_aborted = False

        parse_failures = 0
        for days_ago in range(total_days):
            d = (today_date - timedelta(days=days_ago)).isoformat()
            hrv = None
            sleep = None
            hr_daily = None
            if not hrv_aborted:
                try:
                    hrv = client.get_hrv_data(d)
                    hrv_fail_streak = 0
                except Exception as e:
                    hrv_fail_streak += 1
                    hrv_last_err = e
                    logger.debug("HRV for %s: skipped (%s)", d, e)
                    if hrv_fail_streak >= consec_break:
                        hrv_aborted = True
                        logger.warning(
                            "Garmin HRV aborted after %d consecutive failures "
                            "for user %s: %s",
                            hrv_fail_streak, user_id, hrv_last_err,
                        )
            if not sleep_aborted:
                try:
                    sleep = client.get_sleep_data(d)
                    sleep_fail_streak = 0
                except Exception as e:
                    sleep_fail_streak += 1
                    sleep_last_err = e
                    logger.debug("Sleep for %s: skipped (%s)", d, e)
                    if sleep_fail_streak >= consec_break:
                        sleep_aborted = True
                        logger.warning(
                            "Garmin sleep aborted after %d consecutive failures "
                            "for user %s: %s",
                            sleep_fail_streak, user_id, sleep_last_err,
                        )
            if not hr_aborted:
                try:
                    hr_daily = client.get_heart_rates(d)
                    hr_fail_streak = 0
                except Exception as e:
                    hr_fail_streak += 1
                    hr_last_err = e
                    logger.debug("Heart rates for %s: skipped (%s)", d, e)
                    if hr_fail_streak >= consec_break:
                        hr_aborted = True
                        logger.warning(
                            "Garmin heart_rates aborted after %d consecutive "
                            "failures for user %s: %s",
                            hr_fail_streak, user_id, hr_last_err,
                        )
            # Per-day try/except: keep one malformed Garmin payload from
            # skipping the rest of the window. parse_garmin_recovery is
            # hardened against the known null shapes, but Garmin's schema is
            # undocumented and has regressed before — treat any parse error
            # as "skip this day" rather than aborting the loop.
            try:
                row = parse_garmin_recovery(
                    d, hrv_data=hrv, sleep_data=sleep,
                    training_readiness=tr if days_ago == 0 else None,
                    heart_rates=hr_daily,
                )
            except Exception as e:
                parse_failures += 1
                logger.debug("Recovery parse for %s: skipped (%s)", d, e)
                row = None
            if row:
                recovery_rows.append(row)
            time.sleep(RATE_LIMIT_DELAY)
            if hrv_aborted and sleep_aborted and hr_aborted:
                break

        if total_days and parse_failures >= max(3, total_days // 2):
            logger.warning(
                "Garmin recovery parse failed for %d of %d days (user %s) — "
                "recovery trend will be incomplete",
                parse_failures, total_days, user_id,
            )
    except Exception as e:
        logger.warning("Garmin recovery fetch failed for user %s: %s", user_id, e)

    # DB write is intentionally outside the fetch try/except so a DB error
    # doesn't get mislabelled as a Garmin fetch failure.
    if recovery_rows:
        try:
            # Sleep RHR feeds recovery_data per day for the HRV trend.
            # fitness_data.rest_hr_bpm (the TRIMP reference) is written by
            # write_profile_thresholds above — kept stable, not per-day noisy.
            recovery_count = sync_writer.write_recovery(
                user_id, [], [], {}, db,
                garmin_recovery=recovery_rows,
            )
        except Exception as e:
            logger.warning(
                "Garmin recovery write failed for user %s: %s", user_id, e,
            )

    return {"activities": act_count, "splits": split_count,
            "lactate_threshold": lt_count, "profile": profile_count,
            "daily_metrics": dm_count, "recovery": recovery_count}


def _sync_stryd(user_id: str, creds: dict, from_date: str | None,
                db) -> dict:
    """Fetch Stryd data and write directly to DB."""
    from db import sync_writer
    from sync.stryd_sync import (
        _login_api, fetch_activities_api, fetch_training_plan_api,
        fetch_current_cp,
    )

    stryd_user_id, token = _login_api(creds["email"], creds["password"])
    start = from_date or (date.today() - timedelta(days=14)).isoformat()

    # Fetch current CP from Stryd profile (rolling calculation, may differ from per-activity)
    current_cp = fetch_current_cp(stryd_user_id, token)

    # Activities (power data)
    status = _get_user_status(user_id)
    activity_rows, _raw = fetch_activities_api(stryd_user_id, token, start)
    total = len(activity_rows)
    with _sync_lock:
        status["stryd"]["progress"] = f"Writing {total} activities..."
    # Add activity_type and source for DB writer
    for row in activity_rows:
        row.setdefault("activity_type", "running")
        row.setdefault("source", "stryd")
        # Fallback activity_id if not provided by API
        if not row.get("activity_id"):
            row["activity_id"] = f"stryd_{row.get('date', '')}_{row.get('start_time', '')}"
    act_count = sync_writer.write_activities(user_id, activity_rows, db)

    # Fetch per-activity splits (lap-level power data from activity detail API)
    import time as time_mod
    from sync.stryd_sync import fetch_activity_splits
    all_splits = []
    for idx, raw_act in enumerate(_raw):
        act_id = raw_act.get("id")
        if not act_id:
            continue
        with _sync_lock:
            status["stryd"]["progress"] = f"Fetching splits: {idx + 1}/{total}"
        try:
            splits = fetch_activity_splits(str(act_id), token)
            all_splits.extend(splits)
            time_mod.sleep(0.3)  # Rate limit
        except Exception as e:
            logger.debug("Stryd splits for %s: skipped (%s)", act_id, e)
    split_count = sync_writer.write_splits(user_id, all_splits, db)

    # CP estimates → fitness_data table (for threshold auto-detection)
    from db.models import FitnessData
    cp_by_date: dict = {}
    for row in activity_rows:
        d = row.get("date")
        cp = row.get("cp_estimate")
        if d and cp and cp != "":
            try:
                cp_by_date[d] = float(cp)  # last per date wins
            except (ValueError, TypeError):
                pass
    # Current profile CP for today (the authoritative rolling value from Stryd)
    if current_cp:
        cp_by_date[date.today().isoformat()] = current_cp
    cp_count = 0
    for d_str, cp_val in cp_by_date.items():
        from datetime import datetime as dt_cls
        try:
            d = dt_cls.strptime(str(d_str)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        existing = db.query(FitnessData).filter(
            FitnessData.user_id == user_id,
            FitnessData.date == d,
            FitnessData.metric_type == "cp_estimate",
            FitnessData.source == "stryd",
        ).first()
        if existing:
            if existing.value != cp_val:
                existing.value = cp_val
                cp_count += 1
        else:
            db.add(FitnessData(
                user_id=user_id, date=d,
                metric_type="cp_estimate", value=cp_val, source="stryd",
            ))
            cp_count += 1

    # Training plan
    plan_rows = fetch_training_plan_api(stryd_user_id, token)
    plan_count = sync_writer.write_training_plan(user_id, plan_rows, "stryd", db)

    return {"activities": act_count, "splits": split_count, "cp_estimates": cp_count, "plan": plan_count}


def _sync_strava(user_id: str, creds: dict, from_date: str | None, db) -> dict:
    """Fetch Strava activity data and write directly to DB."""

    import time as time_mod

    from db import sync_writer
    from sync.strava_sync import (
        fetch_activities_api,
        fetch_activity_laps,
        refresh_access_token_if_needed,
    )

    client_id, client_secret = _get_strava_client_config()
    creds, changed = refresh_access_token_if_needed(creds, client_id, client_secret)
    if changed:
        _persist_credentials(user_id, "strava", creds, db)
        # Strava rotates refresh tokens. Commit the rotated credentials before
        # any downstream activity/lap fetch can trigger a rollback.
        db.commit()

    access_token = creds.get("access_token")
    if not access_token:
        raise RuntimeError("Strava credentials missing access_token")

    start = from_date or (date.today() - timedelta(days=14)).isoformat()
    status = _get_user_status(user_id)

    activity_rows, raw_activities = fetch_activities_api(access_token, start)
    total = len(activity_rows)
    with _sync_lock:
        status["strava"]["progress"] = f"Writing {total} activities..."
    for row in activity_rows:
        row.setdefault("activity_type", "other")
        row.setdefault("source", "strava")
    act_count = sync_writer.write_activities(user_id, activity_rows, db)

    all_splits = []
    for idx, raw_act in enumerate(raw_activities):
        activity_id = raw_act.get("id")
        if not activity_id:
            continue
        with _sync_lock:
            status["strava"]["progress"] = f"Fetching laps: {idx + 1}/{total}"
        try:
            all_splits.extend(fetch_activity_laps(str(activity_id), access_token))
            time_mod.sleep(0.2)
        except Exception as exc:
            logger.debug("Strava laps for %s: skipped (%s)", activity_id, exc)
    split_count = sync_writer.write_splits(user_id, all_splits, db)

    return {"activities": act_count, "splits": split_count}


def _sync_oura(user_id: str, creds: dict, from_date: str | None,
               db) -> dict:
    """Fetch Oura data and write directly to DB."""
    from db import sync_writer
    from sync.oura_sync import (
        fetch_sleep_data, fetch_daily_sleep_data, fetch_readiness_data,
        parse_sleep_records, parse_daily_sleep_records, parse_readiness_records,
        merge_daily_sleep_score, select_oura_hrv_per_day,
    )

    token = creds["token"]
    end = date.today().isoformat()
    start = from_date or (date.today() - timedelta(days=7)).isoformat()

    # /sleep gives per-sleep-period detail (HRV, RHR, total/deep/REM,
    # efficiency); /daily_sleep gives the once-per-day sleep score
    # (0–100) that the dashboard renders. Merge by date so each day's
    # detail row carries the canonical sleep_score.
    sleep_raw = fetch_sleep_data(token, start, end)
    sleep_rows = parse_sleep_records(sleep_raw)
    daily_sleep_raw = fetch_daily_sleep_data(token, start, end)
    daily_sleep_rows = parse_daily_sleep_records(daily_sleep_raw)
    sleep_rows = merge_daily_sleep_score(sleep_rows, daily_sleep_rows)

    hrv_by_date = select_oura_hrv_per_day(sleep_raw)

    readiness_raw = fetch_readiness_data(token, start, end)
    readiness_rows = parse_readiness_records(readiness_raw)

    # Write directly to DB
    count = sync_writer.write_recovery(
        user_id, readiness_rows, sleep_rows, hrv_by_date, db
    )
    return {"recovery": count}


def _sync_coros(user_id: str, creds: dict, from_date: str | None,
                db) -> dict:
    """Fetch COROS data and write directly to DB."""
    import time as time_mod

    from db import sync_writer
    from sync.coros_sync import (
        refresh_if_needed,
        fetch_activities,
        fetch_activity_detail,
        fetch_daily_metrics,
        fetch_fitness_summary,
        parse_activities,
        parse_splits,
        parse_daily_metrics as parse_daily,
        parse_fitness_summary as parse_fitness,
        mobile_login,
        fetch_sleep,
        parse_sleep,
    )

    email = creds.get("email", "")
    password = creds.get("password", "")
    region = creds.get("region", "us")

    # Build token creds from stored credentials
    token_creds = {
        "access_token": creds.get("access_token", ""),
        "user_id": creds.get("coros_user_id", ""),
        "region": region,
        "timestamp": creds.get("timestamp", 0),
    }
    token_creds, changed = refresh_if_needed(token_creds, email, password)
    logger.info("COROS hub token refresh: changed=%s, timestamp=%s", changed, token_creds.get("timestamp"))
    if changed:
        updated = dict(creds)
        updated["access_token"] = token_creds["access_token"]
        updated["coros_user_id"] = token_creds["user_id"]
        updated["timestamp"] = token_creds["timestamp"]
        _persist_credentials(user_id, "coros", updated, db)
        db.commit()

    access_token = token_creds["access_token"]
    end = date.today().isoformat()
    start = from_date or (date.today() - timedelta(days=14)).isoformat()

    status = _get_user_status(user_id)

    # Activities — retry with fresh login if token was revoked early
    try:
        raw_activities = fetch_activities(access_token, region, start, end)
    except Exception:
        # Force re-login and retry once
        from sync.coros_sync import login as coros_login
        logger.info("COROS hub token invalid, forcing re-login for user %s", user_id)
        token_creds = coros_login(email, password, region)
        access_token = token_creds["access_token"]
        updated = dict(creds)
        updated["access_token"] = access_token
        updated["coros_user_id"] = token_creds["user_id"]
        updated["timestamp"] = token_creds["timestamp"]
        _persist_credentials(user_id, "coros", updated, db)
        db.commit()
        raw_activities = fetch_activities(access_token, region, start, end)
    activity_rows = parse_activities(raw_activities)
    for row in activity_rows:
        row.setdefault("activity_type", "other")
        row.setdefault("source", "coros")
    act_count = sync_writer.write_activities(user_id, activity_rows, db)

    # Splits (per-activity laps)
    all_splits = []
    total = len(raw_activities)
    for idx, raw_act in enumerate(raw_activities):
        act_id = str(raw_act.get("labelId") or raw_act.get("activityId") or "")
        if not act_id:
            continue
        with _sync_lock:
            status.setdefault("coros", {})["progress"] = f"Fetching splits: {idx + 1}/{total}"
        try:
            detail = fetch_activity_detail(access_token, region, act_id)
            all_splits.extend(parse_splits(act_id, detail))
            time_mod.sleep(0.3)
        except Exception as e:
            logger.debug("COROS splits for %s: skipped (%s)", act_id, e)
    split_count = sync_writer.write_splits(user_id, all_splits, db)

    # Daily metrics (HRV, resting HR, training load)
    # Fetch a wider window (90 days) to ensure enough HRV readings for
    # baseline analysis (requires ≥5 data points).
    dm_count = 0
    recovery_count = 0
    dm_start = (date.today() - timedelta(days=90)).isoformat()
    try:
        raw_daily = fetch_daily_metrics(access_token, region, dm_start, end)
        daily_rows = parse_daily(raw_daily)

        # Write recovery data (HRV, resting HR)
        recovery_rows = [
            r for r in daily_rows
            if r.get("hrv_ms") or r.get("resting_hr")
        ]
        if recovery_rows:
            recovery_count = sync_writer.write_recovery(
                user_id, [], [], {}, db,
                garmin_recovery=recovery_rows,
                recovery_source="coros",
            )
    except Exception as e:
        logger.warning("COROS daily metrics fetch failed for user %s: %s", user_id, e)

    # Sleep data (via mobile API)
    sleep_count = 0
    try:
        mobile_token = creds.get("mobile_access_token", "")
        mobile_ts = int(creds.get("mobile_timestamp", 0))
        # Mobile API tokens expire after ~1 hour — always re-login
        if not mobile_token or (time_mod.time() - mobile_ts) > 3500:
            mobile_creds = mobile_login(email, password, region)
            mobile_token = mobile_creds["mobile_access_token"]
            updated = dict(creds)
            updated["mobile_access_token"] = mobile_token
            updated["mobile_timestamp"] = mobile_creds["mobile_timestamp"]
            _persist_credentials(user_id, "coros", updated, db)
            db.commit()

        raw_sleep = fetch_sleep(mobile_token, region, dm_start, end)
        sleep_rows = parse_sleep(raw_sleep)
        logger.info("COROS sleep: %d nights fetched for user %s, latest dates: %s",
                     len(sleep_rows), user_id,
                     [r["date"] for r in sleep_rows[:5]] if sleep_rows else [])

        if sleep_rows:
            # Merge sleep into recovery rows: write_recovery handles upsert
            sleep_recovery = []
            for sr in sleep_rows:
                row = {"date": sr["date"], "source": "coros"}
                if sr.get("sleep_score"):
                    row["sleep_score"] = sr["sleep_score"]
                if sr.get("total_sleep_sec"):
                    # Convert to hours for write_recovery compatibility
                    row["total_sleep_hours"] = str(round(int(sr["total_sleep_sec"]) / 3600, 2))
                if sr.get("deep_sleep_sec"):
                    row["deep_sleep_sec"] = sr["deep_sleep_sec"]
                if sr.get("rem_sleep_sec"):
                    row["rem_sleep_sec"] = sr["rem_sleep_sec"]
                sleep_recovery.append(row)
            sleep_count = sync_writer.write_recovery(
                user_id, [], [], {}, db,
                garmin_recovery=sleep_recovery,
                recovery_source="coros",
            )
    except Exception as e:
        logger.warning("COROS sleep fetch failed for user %s: %s", user_id, e)

    # Fitness summary (VO2max, LTHR)
    profile_count = 0
    try:
        fitness_raw = fetch_fitness_summary(access_token, region)
        fitness_parsed = parse_fitness(fitness_raw)
        if fitness_parsed:
            profile_count = sync_writer.write_profile_thresholds(
                user_id, fitness_parsed, db,
                source="coros",
            )
    except Exception as e:
        logger.warning("COROS fitness summary fetch failed for user %s: %s", user_id, e)

    return {
        "activities": act_count,
        "splits": split_count,
        "recovery": recovery_count + sleep_count,
        "profile": profile_count,
    }


@router.get("/sync/status")
def get_sync_status(
    user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Return current sync status for this user's connected platforms."""
    from db.models import UserConnection

    # Snapshot runtime status under lock to avoid reading partial updates.
    # _get_user_status acquires _sync_lock internally, so call it outside
    # our own `with _sync_lock` — threading.Lock is not reentrant.
    status = _get_user_status(user_id)
    with _sync_lock:
        runtime_snapshot = {src: dict(info) for src, info in status.items()}

    # Merge with DB connection info (last_sync from DB is more reliable)
    connections = db.query(UserConnection).filter(
        UserConnection.user_id == user_id,
    ).all()
    result = {}
    for conn in connections:
        src = conn.platform
        runtime = runtime_snapshot.get(src, {})
        result[src] = {
            "status": runtime.get("status", "idle"),
            "last_sync": utc_isoformat(conn.last_sync) or runtime.get("last_sync"),
            "error": runtime.get("error"),
            "connected": conn.status in ("connected", "error"),
            "progress": runtime.get("progress"),
        }

    # Include platforms with env var creds but no DB connection (dev mode)
    for src in _DEFAULT_SOURCES:
        if src not in result:
            creds = _get_credentials(user_id, src, db)
            if creds:
                runtime = runtime_snapshot.get(src, {})
                result[src] = {
                    "status": runtime.get("status", "idle"),
                    "last_sync": runtime.get("last_sync"),
                    "error": runtime.get("error"),
                    "connected": True,
                }

    return result


@router.post("/sync/{source}")
def trigger_sync(
    source: str,
    background_tasks: BackgroundTasks,
    body: SyncRequest | None = None,
    user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
) -> dict:
    """Trigger sync for a single source using the user's stored credentials."""
    if source not in _DEFAULT_SOURCES:
        return {"status": "error", "message": f"Unknown source: {source}"}

    creds = _get_credentials(user_id, source, db)
    if not creds:
        return {"status": "error", "message": f"No credentials for {source}. Connect it in Settings first."}

    status = _get_user_status(user_id)
    with _sync_lock:
        if status.get(source, {}).get("status") == "syncing":
            return {"status": "already_syncing", "source": source}
        status[source] = {"status": "syncing", "last_sync": None, "error": None}

    from_date = body.from_date if body else None
    background_tasks.add_task(_run_sync, user_id, source, creds, from_date)
    return {"status": "started", "source": source}


@router.post("/sync")
def trigger_sync_all(
    background_tasks: BackgroundTasks,
    body: SyncRequest | None = None,
    user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
) -> dict:
    """Trigger sync for all connected sources."""
    from_date = body.from_date if body else None
    started = []
    status = _get_user_status(user_id)

    for source in _DEFAULT_SOURCES:
        creds = _get_credentials(user_id, source, db)
        if not creds:
            continue
        with _sync_lock:
            if status.get(source, {}).get("status") == "syncing":
                continue
            status[source] = {"status": "syncing", "last_sync": None, "error": None}
        background_tasks.add_task(_run_sync, user_id, source, creds, from_date)
        started.append(source)

    return {"status": "started", "sources": started}
