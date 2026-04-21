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

_DEFAULT_SOURCES = ["garmin", "stryd", "oura"]


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

        elif source == "stryd":
            counts = _sync_stryd(user_id, creds, from_date, db)

        elif source == "oura":
            counts = _sync_oura(user_id, creds, from_date, db)

        else:
            raise ValueError(f"Unknown source: {source}")

        db.commit()

        # Update last_sync on the connection record
        conn = db.query(UserConnection).filter(
            UserConnection.user_id == user_id,
            UserConnection.platform == source,
        ).first()
        if conn:
            conn.last_sync = datetime.utcnow()
            conn.status = "connected"
            db.commit()

        logger.info("Sync %s for user %s: %s", source, user_id, counts)

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


def _sync_garmin(user_id: str, creds: dict, from_date: str | None,
                 db) -> dict:
    """Fetch Garmin data and write directly to DB."""
    from db import sync_writer
    from garminconnect import Garmin
    from sync.garmin_sync import (
        parse_activities, parse_splits, parse_daily_metrics,
        parse_lactate_threshold, parse_user_profile, RATE_LIMIT_DELAY,
    )
    import time

    client = Garmin(creds["email"], creds["password"],
                    is_cn=creds.get("is_cn", False))
    # The tokenstore must be per-user: garminconnect.Garmin.login() loads any
    # tokens at that path without validating the account they belong to and
    # only falls back to username/password if the files themselves are missing
    # or malformed. A shared path would have every user's sync fetching the
    # first-authenticated user's Garmin data.
    token_dir = _garmin_token_dir(user_id)
    os.makedirs(token_dir, exist_ok=True)
    # garminconnect.login() delegates to garth.load(), which raises
    # FileNotFoundError when the oauth1/oauth2 JSONs aren't present (it only
    # catches AssertionError). Pass the tokenstore only when we have tokens
    # to load; otherwise fall through to username/password auth. Dump after
    # login so the next sync can skip credentials.
    has_tokens = all(
        os.path.isfile(os.path.join(token_dir, name))
        for name in ("oauth1_token.json", "oauth2_token.json")
    )
    client.login(token_dir if has_tokens else None)
    try:
        client.garth.dump(token_dir)
    except AttributeError:
        pass  # garth not available in all garminconnect versions

    end = date.today().isoformat()
    start = from_date or (date.today() - timedelta(days=7)).isoformat()

    # Read configured activity categories from user config.
    # Garmin's search API only accepts top-level types (running, cycling, etc.)
    # not subtypes (trail_running, treadmill_running). We fetch by top-level
    # category — all subtypes are returned automatically.
    from analysis.config import load_config_from_db
    user_config = load_config_from_db(user_id, db)
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
        "strength": "strength_training",
    }
    api_types = list({CATEGORY_TO_API_TYPE.get(c, c) for c in categories})

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

    # User profile — configured max HR and resting HR. These feed
    # api.deps._resolve_thresholds as the authoritative source, so TRIMP uses
    # the user's actual max HR instead of the max-activity fallback.
    profile_count = 0
    try:
        profile_raw = client.get_user_profile()
        profile_parsed = parse_user_profile(profile_raw)
        profile_count = sync_writer.write_profile_thresholds(
            user_id, profile_parsed, db,
        )
    except Exception as e:
        logger.warning("Garmin user profile fetch failed for user %s: %s", user_id, e)

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
        hrv_last_err: Exception | None = None
        sleep_last_err: Exception | None = None
        hrv_aborted = False
        sleep_aborted = False

        recovery_rows = []
        for days_ago in range(total_days):
            d = (today_date - timedelta(days=days_ago)).isoformat()
            hrv = None
            sleep = None
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
            row = parse_garmin_recovery(
                d, hrv_data=hrv, sleep_data=sleep,
                training_readiness=tr if days_ago == 0 else None,
            )
            if row:
                recovery_rows.append(row)
            time.sleep(RATE_LIMIT_DELAY)
            if hrv_aborted and sleep_aborted:
                break

        if recovery_rows:
            # Sleep-data RHR feeds recovery_data for the HRV / recovery trend.
            # The TRIMP rest_hr_bpm threshold is written separately by
            # write_profile_thresholds above from the Garmin user profile —
            # that value is stable across days and the appropriate reference
            # for a threshold input, whereas overnight RHR carries daily noise.
            recovery_count = sync_writer.write_recovery(
                user_id, [], [], {}, db,
                garmin_recovery=recovery_rows,
            )
    except Exception as e:
        logger.warning("Garmin recovery fetch failed for user %s: %s", user_id, e)

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


def _sync_oura(user_id: str, creds: dict, from_date: str | None,
               db) -> dict:
    """Fetch Oura data and write directly to DB."""
    from db import sync_writer
    from sync.oura_sync import (
        fetch_sleep_data, fetch_readiness_data,
        parse_sleep_records, parse_readiness_records,
    )

    token = creds["token"]
    end = date.today().isoformat()
    start = from_date or (date.today() - timedelta(days=7)).isoformat()

    # Fetch raw data
    sleep_raw = fetch_sleep_data(token, start, end)
    sleep_rows = parse_sleep_records(sleep_raw)

    # Extract HRV + resting HR from sleep data (Oura readiness endpoint lacks these)
    hrv_by_date = {}
    for r in sleep_raw:
        d = r.get("day", "")
        hrv_by_date[d] = {
            "hrv_avg": str(r.get("average_hrv", "")),
            "resting_hr": str(r.get("average_heart_rate", "")),
        }

    readiness_raw = fetch_readiness_data(token, start, end)
    readiness_rows = parse_readiness_records(readiness_raw)

    # Write directly to DB
    count = sync_writer.write_recovery(
        user_id, readiness_rows, sleep_rows, hrv_by_date, db
    )
    return {"recovery": count}


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
