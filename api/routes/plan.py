"""Upcoming training plan endpoint with Stryd push integration."""
import json
import logging
import os
from datetime import date, datetime, timezone

import pandas as pd
import requests
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from api.deps import get_dashboard_data

router = APIRouter()

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
_STRYD_PUSH_STATUS_PATH = os.path.join(_DATA_DIR, "ai", "stryd_push_status.json")


@router.get("/plan")
def get_plan() -> dict:
    """Return upcoming planned workouts (today + next 14 days)."""
    data = get_dashboard_data()
    plan_df: pd.DataFrame = data.get("plan", pd.DataFrame())
    today = date.today()

    if plan_df.empty:
        return {"workouts": [], "cp_current": None}

    # Filter for today onwards
    upcoming = plan_df[plan_df["date"] >= today].sort_values("date").head(14)

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


def _load_push_status() -> dict:
    """Load the Stryd push status JSON. Returns {} on missing or corrupt file."""
    if not os.path.exists(_STRYD_PUSH_STATUS_PATH):
        return {}
    try:
        with open(_STRYD_PUSH_STATUS_PATH) as f:
            data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(f"Expected dict, got {type(data).__name__}")
            return data
    except (json.JSONDecodeError, ValueError, OSError) as e:
        logger.warning("Corrupt push status file %s: %s", _STRYD_PUSH_STATUS_PATH, e)
        return {}


def _save_push_status(status: dict) -> None:
    """Save the Stryd push status JSON atomically via temp file + rename."""
    os.makedirs(os.path.dirname(_STRYD_PUSH_STATUS_PATH), exist_ok=True)
    tmp_path = _STRYD_PUSH_STATUS_PATH + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(status, f, indent=2)
    os.replace(tmp_path, _STRYD_PUSH_STATUS_PATH)


@router.get("/plan/stryd-status")
def get_stryd_push_status() -> dict:
    """Return push status for all workouts synced to Stryd."""
    return _load_push_status()


class PushStrydRequest(BaseModel):
    workout_dates: list[str]


@router.post("/plan/push-stryd")
def push_plan_to_stryd(request: PushStrydRequest) -> dict:
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
        user_id, token = _login_api(email, password)
    except Exception as e:
        logger.error("Stryd login failed: %s", e)
        raise HTTPException(status_code=502, detail="Stryd login failed. Check your credentials in sync/.env")

    # Load AI plan data
    data = get_dashboard_data()
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

    push_status = _load_push_status()
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
                user_id=user_id,
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
        _save_push_status(push_status)
    except OSError as e:
        logger.warning("Failed to save push status: %s", e)

    return {"results": results}


@router.delete("/plan/stryd-workout/{workout_id}")
def delete_stryd_workout(workout_id: str) -> dict:
    """Delete a previously pushed workout from Stryd."""
    from sync.stryd_sync import _login_api, delete_workout_api

    load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", "sync", ".env"))
    email = os.environ.get("STRYD_EMAIL")
    password = os.environ.get("STRYD_PASSWORD")
    if not email or not password:
        raise HTTPException(status_code=400, detail="STRYD_EMAIL / STRYD_PASSWORD not configured")

    try:
        user_id, token = _login_api(email, password)
    except Exception as e:
        logger.error("Stryd login failed: %s", e)
        raise HTTPException(status_code=502, detail="Stryd login failed. Check your credentials in sync/.env")

    try:
        delete_workout_api(user_id, token, workout_id)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            pass  # Already deleted on Stryd — proceed to clean local status
        else:
            raise HTTPException(status_code=502, detail=f"Stryd delete failed: {e}")
    except Exception as e:
        logger.error("Stryd delete failed: %s", e)
        raise HTTPException(status_code=502, detail="Failed to delete from Stryd")

    # Remove from push status
    push_status = _load_push_status()
    to_remove = [d for d, info in push_status.items() if info.get("workout_id") == workout_id]
    for d in to_remove:
        del push_status[d]
    _save_push_status(push_status)

    return {"deleted": True, "workout_id": workout_id}
