"""Data sync endpoints — trigger sync per source with background task."""
import os
import traceback
import threading
from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks
from dotenv import load_dotenv
from pydantic import BaseModel, field_validator

from analysis.config import load_config
from api.deps import invalidate_cache

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


# Module-level sync status store
_sync_status: dict[str, dict] = {
    "garmin": {"status": "idle", "last_sync": None, "error": None},
    "stryd": {"status": "idle", "last_sync": None, "error": None},
    "oura": {"status": "idle", "last_sync": None, "error": None},
}
_sync_lock = threading.Lock()


def _ensure_sync_env():
    """Load sync environment variables."""
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "sync", ".env"))


def _get_data_dir() -> str:
    return os.path.join(os.path.dirname(__file__), "..", "..", "data")


def _run_sync(source: str, from_date: str | None = None) -> None:
    """Run sync for a single source. Called in a background thread.

    Args:
        source: Provider name (garmin, stryd, oura).
        from_date: Optional start date (YYYY-MM-DD) for historical backfill.
            If None, each source uses its default lookback (typically 7 days).
    """
    _ensure_sync_env()
    data_dir = _get_data_dir()

    with _sync_lock:
        _sync_status[source] = {"status": "syncing", "last_sync": None, "error": None}

    try:
        if source == "garmin":
            from sync.garmin_sync import sync as garmin_sync
            email = os.environ.get("GARMIN_EMAIL")
            password = os.environ.get("GARMIN_PASSWORD")
            if not email or not password:
                raise ValueError("GARMIN_EMAIL / GARMIN_PASSWORD not set")
            config = load_config()
            is_cn = config.source_options.get("garmin_region") == "cn" or os.environ.get("GARMIN_IS_CN", "").lower() == "true"
            garmin_sync(email, password, data_dir, from_date, is_cn=is_cn)

        elif source == "stryd":
            from sync.stryd_sync import sync as stryd_sync
            email = os.environ.get("STRYD_EMAIL")
            password = os.environ.get("STRYD_PASSWORD")
            if not email or not password:
                raise ValueError("STRYD_EMAIL / STRYD_PASSWORD not set")
            # Default to 14-day lookback to catch late-synced activities
            stryd_from = from_date or (date.today() - timedelta(days=14)).isoformat()
            stryd_sync(data_dir, email=email, password=password, from_date=stryd_from)

        elif source == "oura":
            from sync.oura_sync import sync as oura_sync
            token = os.environ.get("OURA_TOKEN")
            if not token:
                raise ValueError("OURA_TOKEN not set")
            oura_sync(token, data_dir, from_date)

        else:
            raise ValueError(f"Unknown source: {source}")

        with _sync_lock:
            _sync_status[source] = {
                "status": "done",
                "last_sync": datetime.now().isoformat(),
                "error": None,
            }
        invalidate_cache()

    except Exception as e:
        traceback.print_exc()
        with _sync_lock:
            _sync_status[source] = {
                "status": "error",
                "last_sync": None,
                "error": str(e),
            }


@router.get("/sync/status")
def get_sync_status() -> dict:
    """Return current sync status for all sources."""
    with _sync_lock:
        return dict(_sync_status)


@router.post("/sync/{source}")
def trigger_sync(
    source: str,
    background_tasks: BackgroundTasks,
    body: SyncRequest | None = None,
) -> dict:
    """Trigger sync for a single source. Optionally pass from_date for backfill."""
    if source not in _sync_status:
        return {"status": "error", "message": f"Unknown source: {source}"}

    with _sync_lock:
        if _sync_status[source]["status"] == "syncing":
            return {"status": "already_syncing", "source": source}
        _sync_status[source] = {"status": "syncing", "last_sync": None, "error": None}

    from_date = body.from_date if body else None
    background_tasks.add_task(_run_sync, source, from_date)
    return {"status": "started", "source": source}


@router.post("/sync")
def trigger_sync_all(
    background_tasks: BackgroundTasks,
    body: SyncRequest | None = None,
) -> dict:
    """Trigger sync for all configured sources. Optionally pass from_date for backfill."""
    from_date = body.from_date if body else None
    started = []
    for source in _sync_status:
        with _sync_lock:
            if _sync_status[source]["status"] == "syncing":
                continue
            _sync_status[source] = {"status": "syncing", "last_sync": None, "error": None}
        background_tasks.add_task(_run_sync, source, from_date)
        started.append(source)
    return {"status": "started", "sources": started}
