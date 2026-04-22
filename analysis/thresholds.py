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
    """Build ThresholdEstimate from auto-detected provider values only.

    File-based fallback path. ``config_thresholds`` is accepted for call-site
    compatibility with api.deps._resolve_thresholds but its numeric values
    are **not** applied — manual numeric overrides are no longer supported.
    Source selection lives in ``preferences.threshold_sources`` on the DB
    path; the file path doesn't support multi-source disambiguation.
    """
    _ = config_thresholds  # intentionally unused; see docstring
    detected = detect_thresholds(connections, data_dir)
    result = ThresholdEstimate()
    for key in ("cp_watts", "lthr_bpm", "threshold_pace_sec_km", "max_hr_bpm", "rest_hr_bpm"):
        if key in detected:
            setattr(result, key, detected[key]["value"])
    return result
