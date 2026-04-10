"""Shared threshold detection and resolution logic.

Used by both api/deps.py (for metric computation) and api/routes/settings.py
(for the settings UI auto-detect display).
"""
import logging
from typing import Any

from analysis.config import PLATFORM_CAPABILITIES
from analysis.providers import get_fitness_provider
from analysis.providers.models import ThresholdEstimate

logger = logging.getLogger(__name__)


def detect_thresholds(connections: list[str], data_dir: str) -> dict[str, dict[str, Any]]:
    """Auto-detect thresholds from connected fitness providers.

    Returns dict mapping threshold key -> {"value": float, "source": platform_name}.
    Only includes non-None detected values.
    """
    result: dict[str, dict[str, Any]] = {}

    for conn in connections:
        caps = PLATFORM_CAPABILITIES.get(conn, {})
        if not caps.get("fitness"):
            continue
        try:
            provider = get_fitness_provider(conn)
            detected = provider.detect_thresholds(data_dir)
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
        except Exception:
            logger.warning("Threshold detection failed for %s", conn, exc_info=True)
            continue

    return result


def resolve_thresholds_to_estimate(
    config_thresholds: dict, connections: list[str], data_dir: str,
) -> ThresholdEstimate:
    """Build ThresholdEstimate from auto-detect + manual config overrides.

    Auto-detects from connected providers, then applies manual overrides.
    Used by deps.py for metric computation.
    """
    detected = detect_thresholds(connections, data_dir)
    result = ThresholdEstimate()

    # Apply auto-detected values
    for key in ("cp_watts", "lthr_bpm", "threshold_pace_sec_km", "max_hr_bpm", "rest_hr_bpm"):
        if key in detected:
            setattr(result, key, detected[key]["value"])

    # Manual overrides from config
    t = config_thresholds
    if t.get("cp_watts"):
        result.cp_watts = float(t["cp_watts"])
    if t.get("lthr_bpm"):
        result.lthr_bpm = float(t["lthr_bpm"])
    if t.get("threshold_pace_sec_km"):
        result.threshold_pace_sec_km = float(t["threshold_pace_sec_km"])
    if t.get("max_hr_bpm"):
        result.max_hr_bpm = float(t["max_hr_bpm"])
    if t.get("rest_hr_bpm"):
        result.rest_hr_bpm = float(t["rest_hr_bpm"])

    return result
