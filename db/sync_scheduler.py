"""Background sync scheduler — per-user, staggered.

Runs as a daemon thread started on app boot. Every CHECK_INTERVAL seconds,
scans user_connections for stale entries and triggers sync for each.
Syncs are staggered (one at a time, small delay between) to avoid rate limits.
"""
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SEC = 600  # Check every 10 minutes
DEFAULT_SYNC_INTERVAL_HOURS = 6
ALLOWED_SYNC_INTERVAL_HOURS = (6, 12, 24)
DELAY_BETWEEN_SYNCS_SEC = 5  # Stagger between user/platform syncs

_scheduler_thread: threading.Thread | None = None
_stop_event = threading.Event()


def normalize_sync_interval_hours(value: object) -> int:
    """Validate and normalize sync frequency to one of the allowed options."""
    try:
        hours = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Sync interval must be an integer hour value.") from exc
    if hours not in ALLOWED_SYNC_INTERVAL_HOURS:
        raise ValueError(
            f"Sync interval must be one of {ALLOWED_SYNC_INTERVAL_HOURS} hours."
        )
    return hours


def get_user_sync_interval_hours(
    source_options: dict | None, *, user_id: str | None = None
) -> int:
    """Return effective sync interval from source_options with safe fallback.

    Invalid stored values fall back to the default rather than raising — the
    background scheduler must keep running for other users even if one row is
    corrupt — but bad input is logged so config drift is visible.
    """
    if source_options is None:
        return DEFAULT_SYNC_INTERVAL_HOURS
    if not isinstance(source_options, dict):
        logger.warning(
            "source_options for user=%s is %s, expected dict; using default %dh",
            user_id, type(source_options).__name__, DEFAULT_SYNC_INTERVAL_HOURS,
        )
        return DEFAULT_SYNC_INTERVAL_HOURS
    raw = source_options.get("sync_interval_hours")
    if raw is None:
        return DEFAULT_SYNC_INTERVAL_HOURS
    try:
        return normalize_sync_interval_hours(raw)
    except ValueError as exc:
        logger.warning(
            "Invalid sync_interval_hours=%r for user=%s; falling back to %dh: %s",
            raw, user_id, DEFAULT_SYNC_INTERVAL_HOURS, exc,
        )
        return DEFAULT_SYNC_INTERVAL_HOURS


def start_scheduler():
    """Start the background sync scheduler. Safe to call multiple times."""
    global _scheduler_thread
    if _scheduler_thread is not None and _scheduler_thread.is_alive():
        return
    _stop_event.clear()
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
    _scheduler_thread.start()
    logger.info("Sync scheduler started (check every %ds)", CHECK_INTERVAL_SEC)


def stop_scheduler():
    """Stop the background sync scheduler."""
    _stop_event.set()
    if _scheduler_thread:
        _scheduler_thread.join(timeout=5)
    logger.info("Sync scheduler stopped")


def _scheduler_loop():
    """Main scheduler loop — runs in a background thread."""
    # Wait a bit on startup to let the app fully initialize
    _stop_event.wait(30)

    while not _stop_event.is_set():
        try:
            _check_and_sync()
        except Exception:
            logger.exception("Scheduler tick failed")
        _stop_event.wait(CHECK_INTERVAL_SEC)


def _check_and_sync():
    """Check all user connections and sync stale ones."""
    from db.session import init_db, SessionLocal
    from db.models import UserConnection, UserConfig

    init_db()
    db = SessionLocal()
    try:
        connections = db.query(UserConnection).filter(
            UserConnection.status.in_(["connected", "error"]),
        ).all()

        now = datetime.utcnow()
        sync_intervals_by_user: dict[str, int] = {}
        for conn in connections:
            if conn.user_id not in sync_intervals_by_user:
                # Isolate per-user config lookup so one bad row can't skip every
                # remaining user this tick.
                try:
                    config = (
                        db.query(UserConfig.source_options)
                        .filter(UserConfig.user_id == conn.user_id)
                        .first()
                    )
                    source_options = config[0] if config else None
                    sync_intervals_by_user[conn.user_id] = get_user_sync_interval_hours(
                        source_options, user_id=conn.user_id,
                    )
                except Exception:
                    logger.exception(
                        "Failed to load sync interval for user=%s; using default %dh",
                        conn.user_id, DEFAULT_SYNC_INTERVAL_HOURS,
                    )
                    sync_intervals_by_user[conn.user_id] = DEFAULT_SYNC_INTERVAL_HOURS
            interval_hours = sync_intervals_by_user[conn.user_id]
            last = conn.last_sync
            if last and (now - last) < timedelta(hours=interval_hours):
                continue  # Not stale yet

            logger.info(
                "Scheduled sync: user=%s platform=%s (last=%s interval=%sh)",
                conn.user_id, conn.platform, last, interval_hours,
            )
            try:
                _sync_connection(conn.user_id, conn.platform, db)
                time.sleep(DELAY_BETWEEN_SYNCS_SEC)
            except Exception:
                logger.exception(
                    "Scheduled sync failed: user=%s platform=%s",
                    conn.user_id, conn.platform,
                )
    finally:
        db.close()


def _sync_connection(user_id: str, platform: str, db):
    """Sync a single user-platform connection using encrypted credentials.

    Uses the sync route's fetch + DB write functions (no CSV intermediate).
    """
    from db.models import UserConnection
    from db.crypto import get_vault

    conn = db.query(UserConnection).filter(
        UserConnection.user_id == user_id,
        UserConnection.platform == platform,
    ).first()
    if not conn or not conn.encrypted_credentials:
        logger.warning("No credentials for user=%s platform=%s", user_id, platform)
        return

    # Decrypt credentials
    vault = get_vault()
    creds_json = vault.decrypt(conn.encrypted_credentials, conn.wrapped_dek)
    creds = json.loads(creds_json)

    # Use the sync route's direct DB write functions
    from api.routes.sync import _sync_garmin, _sync_stryd, _sync_oura

    if platform == "garmin":
        counts = _sync_garmin(user_id, creds, None, db)
    elif platform == "stryd":
        counts = _sync_stryd(user_id, creds, None, db)
    elif platform == "oura":
        counts = _sync_oura(user_id, creds, None, db)
    else:
        logger.warning("Unknown platform: %s", platform)
        return

    db.commit()

    # Update last_sync
    conn.last_sync = datetime.utcnow()
    conn.status = "connected"
    db.commit()
    logger.info("Sync complete: user=%s platform=%s counts=%s", user_id, platform, counts)
