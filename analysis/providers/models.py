"""Canonical data models for the provider layer."""
from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass
class ThresholdEstimate:
    """Auto-detected or manually set threshold values."""

    cp_watts: float | None = None
    lthr_bpm: float | None = None
    threshold_pace_sec_km: float | None = None
    max_hr_bpm: float | None = None
    rest_hr_bpm: float | None = None
    source: Literal["auto", "manual"] = "auto"
    detected_date: date | None = None


# ---------------------------------------------------------------------------
# Canonical column name constants (documentation + validation)
# ---------------------------------------------------------------------------

ACTIVITY_REQUIRED = ["activity_id", "date", "distance_km", "duration_sec", "activity_type"]
ACTIVITY_OPTIONAL = [
    "start_time",
    "avg_power", "max_power",
    "avg_hr", "max_hr",
    "avg_pace_sec_km",
    "elevation_gain_m", "avg_cadence",
    "rss", "trimp", "rtss", "cp_estimate", "load_score",
]

# Standard activity_type values
ACTIVITY_TYPES = [
    "running", "trail_running", "cycling", "swimming",
    "strength", "walking", "hiking", "other",
]

SPLIT_REQUIRED = ["activity_id", "split_num", "duration_sec"]
SPLIT_OPTIONAL = [
    "distance_km", "avg_power", "avg_hr", "max_hr",
    "avg_pace_sec_km", "avg_cadence", "elevation_change_m",
]

RECOVERY_REQUIRED = ["date"]
RECOVERY_OPTIONAL = [
    "sleep_score", "readiness_score", "hrv_avg", "resting_hr",
    "total_sleep_sec", "deep_sleep_sec", "rem_sleep_sec",
    "body_temp_delta",
]

FITNESS_REQUIRED = ["date"]
FITNESS_OPTIONAL = [
    "vo2max", "training_status", "training_readiness",
    "cp_estimate", "lthr_bpm", "lt_pace_sec_km",
    "leg_spring_stiffness", "avg_oscillation", "avg_stride_length",
]

PLAN_REQUIRED = ["date", "workout_type"]
PLAN_OPTIONAL = [
    "planned_duration_min", "planned_distance_km",
    "target_power_min", "target_power_max",
    "target_hr_min", "target_hr_max",
    "target_pace_min", "target_pace_max",
    "workout_description",
]
