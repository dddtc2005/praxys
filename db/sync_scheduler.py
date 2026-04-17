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
DELAY_BETWEEN_SYNCS_SEC = 5  # Stagger between user/platform syncs

_scheduler_thread: threading.Thread | None = None
_stop_event = threading.Event()


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
    from db.models import UserConnection

    init_db()
    db = SessionLocal()
    try:
        connections = db.query(UserConnection).filter(
            UserConnection.status.in_(["connected", "error"]),
        ).all()

        now = datetime.utcnow()
        for conn in connections:
            interval_hours = DEFAULT_SYNC_INTERVAL_HOURS
            last = conn.last_sync
            if last and (now - last) < timedelta(hours=interval_hours):
                continue  # Not stale yet

            logger.info(
                "Scheduled sync: user=%s platform=%s (last=%s)",
                conn.user_id, conn.platform, last,
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
