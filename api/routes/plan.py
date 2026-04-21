"""Upcoming training plan endpoint with Stryd push integration."""
import json
import logging
import os
from datetime import date, datetime, timezone

import pandas as pd
import requests
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from api.auth import get_data_user_id, require_write_access
from api.deps import get_dashboard_data
from db.session import get_db

router = APIRouter()

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
_STRYD_PUSH_STATUS_DIR = os.path.join(_DATA_DIR, "ai", "stryd_push_status")


def _stryd_push_status_path(user_id: str) -> str:
    """Per-user push-status path.

    Must be per-user: a shared file would let any caller of
    ``GET /api/plan/stryd-status`` see every other user's workout IDs and
    push timestamps. UUID user_ids keep filenames collision-free and
    filesystem-safe.

    A legacy single-file layout at ``data/ai/stryd_push_status.json`` may
    still exist on older deployments — this code does not read or migrate
    it. Operators should delete that orphan file on deploy; leaving it in
    place only means historical push-state that the UI won't show. No user
    data is lost.
    """
    return os.path.join(_STRYD_PUSH_STATUS_DIR, f"{user_id}.json")


@router.get("/plan")
def get_plan(
    user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Return all upcoming planned workouts (today onwards)."""
    data = get_dashboard_data(user_id=user_id, db=db)
    plan_df: pd.DataFrame = data.get("plan", pd.DataFrame())
    today = date.today()

    if plan_df.empty:
        return {"workouts": [], "cp_current": None}

    # Filter for today onwards — return all (frontend handles pagination)
    upcoming = plan_df[plan_df["date"] >= today].sort_values("date")

    workouts = []
    for _, row in upcoming.iterrows():
        workout = {
            "date": row["date"].isoformat() if hasattr(row["date"], "isoformat") else str(row["date"]),
            "workout_type": row.get("workout_type", ""),
        }
        for field, csv_col in [
            ("duration_min", "planned_duration_min"),
            ("distance_km", "planned_distance_km"),
            ("power_min", "target_power_min"),
            ("power_max", "target_power_max"),
            ("description", "workout_description"),
        ]:
            val = row.get(csv_col)
            if pd.notna(val) and val != "":
                workout[field] = float(val) if field != "description" else str(val)
        workouts.append(workout)

    # Get current CP from the latest activity data if available
    cp_current = None
    signal = data.get("signal", {})
    if isinstance(signal, dict):
        plan = signal.get("plan", {})
        if isinstance(plan, dict) and plan.get("power_max"):
            cp_current = plan.get("power_max")

    return {"workouts": workouts, "cp_current": cp_current}


def _load_push_status(user_id: str) -> dict:
    """Load a user's Stryd push status JSON.

    Returns {} when the file is absent. On corruption, quarantines the file
    (renames to ``*.corrupt-<timestamp>``) and returns {} — the subsequent
    save would otherwise overwrite it with an empty dict and destroy any
    recoverable content.
    """
    path = _stryd_push_status_path(user_id)
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(f"Expected dict, got {type(data).__name__}")
            return data
    except (json.JSONDecodeError, ValueError, OSError) as e:
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        quarantine = f"{path}.corrupt-{stamp}"
        try:
            os.replace(path, quarantine)
            logger.error(
                "Quarantined corrupt push status file for user=%s at %s: %s",
                user_id, quarantine, e,
            )
        except OSError as rename_err:
            logger.error(
                "Corrupt push status file for user=%s at %s (quarantine failed: %s): %s",
                user_id, path, rename_err, e,
            )
        return {}


def _save_push_status(user_id: str, status: dict) -> None:
    """Save a user's Stryd push status JSON atomically via temp file + rename."""
    path = _stryd_push_status_path(user_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(status, f, indent=2)
        os.replace(tmp_path, path)
    except OSError:
        # Don't leave a half-written tmp file behind on rename failures.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


@router.get("/plan/stryd-status")
def get_stryd_push_status(
    user_id: str = Depends(get_data_user_id),
) -> dict:
    """Return push status for all workouts synced to Stryd."""
    return _load_push_status(user_id)


class PushStrydRequest(BaseModel):
    workout_dates: list[str]


@router.post("/plan/push-stryd")
def push_plan_to_stryd(
    request: PushStrydRequest,
    current_user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
) -> dict:
    """Push selected AI plan workouts to Stryd calendar.

    Converts AI plan workouts to Stryd structured format and uploads them.
    """
    from sync.stryd_sync import (
        _login_api,
        _STRYD_WORKOUT_TYPES,
        build_workout_blocks,
        create_workout_api,
    )

    # Load Stryd credentials
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "sync", ".env"))
    email = os.environ.get("STRYD_EMAIL")
    password = os.environ.get("STRYD_PASSWORD")
    if not email or not password:
        raise HTTPException(status_code=400, detail="STRYD_EMAIL / STRYD_PASSWORD not configured")

    # Login to Stryd
    try:
        stryd_user_id, token = _login_api(email, password)
    except Exception as e:
        logger.error("Stryd login failed: %s", e)
        raise HTTPException(status_code=502, detail="Stryd login failed. Check your credentials in sync/.env")

    # Load AI plan data
    data = get_dashboard_data(user_id=current_user_id, db=db)
    plan_df: pd.DataFrame = data.get("plan", pd.DataFrame())
    if plan_df.empty:
        raise HTTPException(status_code=404, detail="No training plan found")

    # Get current CP for block building
    cp_watts = None
    latest_cp = data.get("latest_cp")
    if latest_cp and float(latest_cp) > 0:
        cp_watts = float(latest_cp)
    # Fallback: try from latest activities
    if not cp_watts:
        activities = data.get("activities", pd.DataFrame())
        if not isinstance(activities, pd.DataFrame) or activities.empty:
            pass
        else:
            cp_col = "cp_estimate" if "cp_estimate" in activities.columns else None
            if cp_col:
                valid_cp = activities[cp_col].dropna()
                if not valid_cp.empty:
                    cp_watts = float(valid_cp.iloc[-1])
    if not cp_watts:
        raise HTTPException(
            status_code=422,
            detail="Cannot determine Critical Power from your data. Ensure recent activities with power data are synced before pushing to Stryd.",
        )

    push_status = _load_push_status(current_user_id)
    results = []

    for workout_date in request.workout_dates:
        # Skip rest days
        matching = plan_df[plan_df["date"].astype(str) == workout_date]
        if matching.empty:
            results.append({"date": workout_date, "status": "error", "error": "No workout found for this date"})
            continue

        row = matching.iloc[0]
        workout_type = str(row.get("workout_type", ""))

        # Skip rest days
        if workout_type.lower() in ("rest", "off"):
            results.append({"date": workout_date, "status": "error", "error": "Rest day — nothing to push"})
            continue

        workout = row.to_dict()
        # Convert date objects to strings for the dict
        for k, v in workout.items():
            if hasattr(v, "isoformat"):
                workout[k] = v.isoformat()

        try:
            blocks = build_workout_blocks(workout, cp_watts)
            stryd_type = _STRYD_WORKOUT_TYPES.get(workout_type.lower(), "")
            title = f"{workout_type.replace('_', ' ').title()}"
            description = str(row.get("workout_description", ""))

            result = create_workout_api(
                user_id=stryd_user_id,
                token=token,
                workout_date=workout_date,
                title=title,
                blocks=blocks,
                workout_type=stryd_type,
                description=description,
            )

            workout_id = str(result.get("id", ""))
            push_status[workout_date] = {
                "workout_id": workout_id,
                "pushed_at": datetime.now(timezone.utc).isoformat(),
                "status": "pushed",
            }
            results.append({"date": workout_date, "status": "success", "workout_id": workout_id})

        except requests.HTTPError as e:
            detail = str(e)
            if e.response is not None:
                try:
                    detail = e.response.json().get("message", detail)
                except (ValueError, AttributeError):
                    pass
            results.append({"date": workout_date, "status": "error", "error": f"Stryd API error: {detail}"})
        except Exception as e:
            logger.error("Failed to push workout for %s: %s: %s", workout_date, type(e).__name__, e)
            results.append({"date": workout_date, "status": "error", "error": str(e)})

    try:
        _save_push_status(current_user_id, push_status)
    except OSError as e:
        logger.warning("Failed to save push status: %s", e)

    return {"results": results}


@router.delete("/plan/stryd-workout/{workout_id}")
def delete_stryd_workout(
    workout_id: str,
    current_user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
) -> dict:
    """Delete a previously pushed workout from Stryd."""
    from sync.stryd_sync import _login_api, delete_workout_api

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "sync", ".env"))
    email = os.environ.get("STRYD_EMAIL")
    password = os.environ.get("STRYD_PASSWORD")
    if not email or not password:
        raise HTTPException(status_code=400, detail="STRYD_EMAIL / STRYD_PASSWORD not configured")

    try:
        stryd_user_id, token = _login_api(email, password)
    except Exception as e:
        logger.error("Stryd login failed: %s", e)
        raise HTTPException(status_code=502, detail="Stryd login failed. Check your credentials in sync/.env")

    try:
        delete_workout_api(stryd_user_id, token, workout_id)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            pass  # Already deleted on Stryd — proceed to clean local status
        else:
            raise HTTPException(status_code=502, detail=f"Stryd delete failed: {e}")
    except Exception as e:
        logger.error("Stryd delete failed: %s", e)
        raise HTTPException(status_code=502, detail="Failed to delete from Stryd")

    # Remove from push status
    push_status = _load_push_status(current_user_id)
    to_remove = [d for d, info in push_status.items() if info.get("workout_id") == workout_id]
    for d in to_remove:
        del push_status[d]
    _save_push_status(current_user_id, push_status)

    return {"deleted": True, "workout_id": workout_id}
