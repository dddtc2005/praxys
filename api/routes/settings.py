"""User settings endpoints."""
import os
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from analysis.config import load_config, save_config, TrainingBase, PLATFORM_CAPABILITIES
from analysis.providers import available_providers, get_fitness_provider
from analysis.providers.models import ThresholdEstimate
from analysis.training_base import get_display_config
from api.deps import invalidate_cache

router = APIRouter()


class SettingsUpdate(BaseModel):
    """Partial update for user settings."""
    connections: list[str] | None = None
    preferences: dict[str, str] | None = None
    training_base: TrainingBase | None = None
    thresholds: dict[str, Any] | None = None
    zones: dict[str, list[float]] | None = None
    goal: dict[str, Any] | None = None
    source_options: dict[str, Any] | None = None


def _detect_thresholds(connections: list[str]) -> dict:
    """Auto-detect thresholds from connected fitness providers."""
    base_dir = os.path.join(os.path.dirname(__file__), "..", "..")
    data_dir = os.path.join(base_dir, "data")

    result: dict[str, Any] = {}

    for conn in connections:
        caps = PLATFORM_CAPABILITIES.get(conn, {})
        if not caps.get("fitness"):
            continue
        try:
            provider = get_fitness_provider(conn)
            detected = provider.detect_thresholds(data_dir)
            # Collect non-None values with their source
            if detected.cp_watts and "cp_watts" not in result:
                result["cp_watts"] = {"value": detected.cp_watts, "source": conn}
            if detected.lthr_bpm and "lthr_bpm" not in result:
                result["lthr_bpm"] = {"value": detected.lthr_bpm, "source": conn}
            if detected.threshold_pace_sec_km and "threshold_pace_sec_km" not in result:
                result["threshold_pace_sec_km"] = {"value": detected.threshold_pace_sec_km, "source": conn}
            if detected.max_hr_bpm and "max_hr_bpm" not in result:
                result["max_hr_bpm"] = {"value": detected.max_hr_bpm, "source": conn}
            if detected.rest_hr_bpm and "rest_hr_bpm" not in result:
                result["rest_hr_bpm"] = {"value": detected.rest_hr_bpm, "source": conn}
        except KeyError:
            continue  # Provider not registered for this connection
        except Exception as e:
            print(f"  Warning: threshold detection failed for {conn}: {e}")
            continue

    return result


def resolve_thresholds(config_thresholds: dict, detected: dict) -> dict:
    """Merge auto-detected thresholds with manual overrides.

    Manual overrides (source == 'manual') take precedence.
    Returns the effective threshold values.
    """
    effective: dict[str, Any] = {}
    is_manual = config_thresholds.get("source") == "manual"

    for key in ["cp_watts", "lthr_bpm", "threshold_pace_sec_km", "max_hr_bpm", "rest_hr_bpm"]:
        manual_val = config_thresholds.get(key)
        auto_val = detected.get(key, {}).get("value") if key in detected else None

        if is_manual and manual_val is not None:
            effective[key] = {"value": manual_val, "origin": "manual"}
        elif auto_val is not None:
            effective[key] = {"value": auto_val, "origin": f"auto ({detected[key]['source']})"}
        elif manual_val is not None:
            effective[key] = {"value": manual_val, "origin": "manual"}
        else:
            effective[key] = {"value": None, "origin": "none"}

    return effective


@router.get("/settings")
def get_settings() -> dict:
    """Return current user config, platform capabilities, detected thresholds, and display config."""
    config = load_config()
    avail = available_providers()
    detected = _detect_thresholds(config.connections)
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
def update_settings(body: SettingsUpdate) -> dict:
    """Update user settings. Invalidates dashboard cache."""
    config = load_config()

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

    save_config(config)
    invalidate_cache()

    return {
        "status": "ok",
        "config": asdict(config),
        "display": get_display_config(config.training_base),
    }
