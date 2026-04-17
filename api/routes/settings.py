"""User settings endpoints.

Supports both file-based (backward compat) and DB-based config persistence.
When user_id and db are available (from auth), uses DB; otherwise falls back to files.
"""
import logging
import os
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from analysis.config import (
    load_config,
    save_config,
    load_config_from_db,
    save_config_to_db,
    TrainingBase,
    PLATFORM_CAPABILITIES,
)
from analysis.providers import available_providers
from analysis.thresholds import detect_thresholds
from analysis.training_base import get_display_config
from api.auth import get_data_user_id, require_write_access
from db.session import get_db

router = APIRouter()


class SettingsUpdate(BaseModel):
    """Partial update for user settings."""

    display_name: str | None = None
    unit_system: str | None = None
    connections: list[str] | None = None
    preferences: dict[str, str] | None = None
    training_base: TrainingBase | None = None
    thresholds: dict[str, Any] | None = None
    zones: dict[str, list[float]] | None = None
    goal: dict[str, Any] | None = None
    source_options: dict[str, Any] | None = None


def _detect_thresholds_from_db(user_id: str, db) -> dict:
    """Auto-detect thresholds from fitness_data in the database.

    Returns dict mapping threshold key -> {"value": float, "source": platform_name}.
    """
    from db.models import FitnessData

    result: dict = {}
    # Map metric_type → threshold key
    metric_map = {
        "cp_estimate": ("cp_watts", "stryd"),
        "lthr_bpm": ("lthr_bpm", "garmin"),
        "lt_pace_sec_km": ("threshold_pace_sec_km", "garmin"),
    }

    for metric_type, (threshold_key, default_source) in metric_map.items():
        row = (
            db.query(FitnessData)
            .filter(
                FitnessData.user_id == user_id,
                FitnessData.metric_type == metric_type,
                FitnessData.value.isnot(None),
            )
            .order_by(FitnessData.date.desc())
            .first()
        )
        if row and row.value:
            result[threshold_key] = {
                "value": round(float(row.value), 1),
                "source": row.source or default_source,
            }

    # Max HR and resting HR from fitness_data
    for metric_type, threshold_key in [("max_hr_bpm", "max_hr_bpm"), ("rest_hr_bpm", "rest_hr_bpm")]:
        row = (
            db.query(FitnessData)
            .filter(
                FitnessData.user_id == user_id,
                FitnessData.metric_type == metric_type,
                FitnessData.value.isnot(None),
            )
            .order_by(FitnessData.date.desc())
            .first()
        )
        if row and row.value:
            result[threshold_key] = {
                "value": round(float(row.value), 1),
                "source": row.source or "garmin",
            }

    # Fallback: detect max HR from activities if not in fitness_data
    if "max_hr_bpm" not in result:
        from db.models import Activity
        from sqlalchemy import func
        max_hr = db.query(func.max(Activity.max_hr)).filter(
            Activity.user_id == user_id,
            Activity.max_hr.isnot(None),
        ).scalar()
        if max_hr:
            result["max_hr_bpm"] = {"value": round(float(max_hr), 1), "source": "activities"}

    return result


def resolve_thresholds(config_thresholds: dict, detected: dict) -> dict:
    """Merge auto-detected thresholds with manual overrides.

    Manual overrides (source == 'manual') take precedence.
    Returns the effective threshold values.
    """
    effective: dict[str, Any] = {}
    is_manual = config_thresholds.get("source") == "manual"

    for key in [
        "cp_watts",
        "lthr_bpm",
        "threshold_pace_sec_km",
        "max_hr_bpm",
        "rest_hr_bpm",
    ]:
        manual_val = config_thresholds.get(key)
        auto_val = detected.get(key, {}).get("value") if key in detected else None

        if is_manual and manual_val is not None:
            effective[key] = {"value": manual_val, "origin": "manual"}
        elif auto_val is not None:
            effective[key] = {
                "value": auto_val,
                "origin": f"auto ({detected[key]['source']})",
            }
        elif manual_val is not None:
            effective[key] = {"value": manual_val, "origin": "manual"}
        else:
            effective[key] = {"value": None, "origin": "none"}

    return effective


@router.get("/settings")
def get_settings(
    user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Return current user config, platform capabilities, detected thresholds, and display config."""
    config = load_config_from_db(user_id, db)
    avail = available_providers()
    detected = _detect_thresholds_from_db(user_id, db)
    effective = resolve_thresholds(config.thresholds, detected)

    return {
        "config": asdict(config),
        "platform_capabilities": PLATFORM_CAPABILITIES,
        "available_providers": {
            "activities": avail.get("activities", []),
            "recovery": avail.get("recovery", []),
            "fitness": avail.get("fitness", []),
            "plan": avail.get("plan", []),
        },
        "available_bases": ["power", "hr", "pace"],
        "display": get_display_config(config.training_base),
        "detected_thresholds": detected,
        "effective_thresholds": effective,
    }


@router.put("/settings")
def update_settings(
    body: SettingsUpdate,
    user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
) -> dict:
    """Update user settings and persist to database."""
    config = load_config_from_db(user_id, db)

    if body.display_name is not None:
        config.display_name = body.display_name
    if body.unit_system is not None:
        config.unit_system = body.unit_system
    if body.training_base is not None:
        config.training_base = body.training_base
    if body.connections is not None:
        config.connections = body.connections
    if body.preferences is not None:
        config.preferences.update(body.preferences)
    if body.thresholds is not None:
        config.thresholds.update(body.thresholds)
    if body.zones is not None:
        config.zones.update(body.zones)
    if body.goal is not None:
        config.goal.update(body.goal)
    if body.source_options is not None:
        config.source_options.update(body.source_options)

    save_config_to_db(user_id, config, db)

    return {
        "status": "ok",
        "config": asdict(config),
        "display": get_display_config(config.training_base),
    }


# ---------------------------------------------------------------------------
# Platform connection management
# ---------------------------------------------------------------------------


class ConnectPlatformRequest(BaseModel):
    """Credentials for connecting a platform."""
    # Garmin / Stryd
    email: str | None = None
    password: str | None = None
    # Oura
    token: str | None = None
    # Garmin-specific
    is_cn: bool = False


@router.get("/settings/connections")
def get_connections(
    user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Return connected platforms and their status (credentials are never returned)."""
    from db.models import UserConnection

    connections = db.query(UserConnection).filter(
        UserConnection.user_id == user_id,
    ).all()

    result = {}
    for conn in connections:
        result[conn.platform] = {
            "status": conn.status,
            "last_sync": conn.last_sync.isoformat() if conn.last_sync else None,
            "has_credentials": conn.encrypted_credentials is not None,
        }
    return {"connections": result}


@router.post("/settings/connections/{platform}")
def connect_platform(
    platform: str,
    body: ConnectPlatformRequest,
    user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
) -> dict:
    """Connect a platform by storing encrypted credentials."""
    import json as json_mod
    from db.models import UserConnection
    from db.crypto import get_vault

    if platform not in PLATFORM_CAPABILITIES:
        return {"status": "error", "message": f"Unknown platform: {platform}"}

    # Build credentials dict based on platform
    if platform in ("garmin", "stryd"):
        if not body.email or not body.password:
            return {"status": "error", "message": "email and password required"}
        creds = {"email": body.email, "password": body.password}
        if platform == "garmin":
            creds["is_cn"] = body.is_cn
    elif platform == "oura":
        if not body.token:
            return {"status": "error", "message": "token required"}
        creds = {"token": body.token}
    else:
        return {"status": "error", "message": f"Unsupported platform: {platform}"}

    # Encrypt credentials
    vault = get_vault()
    encrypted_data, wrapped_dek = vault.encrypt(json_mod.dumps(creds))

    # Upsert connection
    conn = db.query(UserConnection).filter(
        UserConnection.user_id == user_id,
        UserConnection.platform == platform,
    ).first()

    # Build preferences from platform capabilities
    caps = PLATFORM_CAPABILITIES.get(platform, {})
    prefs = {k: v for k, v in caps.items() if v}

    if conn:
        conn.encrypted_credentials = encrypted_data
        conn.wrapped_dek = wrapped_dek
        conn.status = "connected"
        conn.preferences = prefs
    else:
        conn = UserConnection(
            user_id=user_id,
            platform=platform,
            encrypted_credentials=encrypted_data,
            wrapped_dek=wrapped_dek,
            status="connected",
            preferences=prefs,
        )
        db.add(conn)

    db.commit()
    return {"status": "connected", "platform": platform}


@router.delete("/settings/connections/{platform}")
def disconnect_platform(
    platform: str,
    user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
) -> dict:
    """Disconnect a platform — deletes stored credentials."""
    from db.models import UserConnection

    conn = db.query(UserConnection).filter(
        UserConnection.user_id == user_id,
        UserConnection.platform == platform,
    ).first()
    if conn:
        db.delete(conn)
        db.commit()
    return {"status": "disconnected", "platform": platform}
