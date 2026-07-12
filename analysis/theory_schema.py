"""Pydantic validators for YAML theory files.

Each pillar has specific required parameters. Validation runs at load time
to catch missing or wrong-type fields early instead of silent defaults.
"""
from pydantic import BaseModel, Field, model_validator
from typing import Any


class LoadTheoryParams(BaseModel):
    """Required params for load-pillar theories (e.g., banister_pmc)."""
    ctl_time_constant: int
    atl_time_constant: int
    rss_exponent: float = 2.0
    trimp_k_male: float = 1.92
    trimp_k_female: float = 1.67


class RecoveryTheoryParams(BaseModel):
    """Required params for recovery-pillar theories (e.g., hrv_based)."""
    rolling_days: int = Field(default=7, ge=2)
    baseline_days: int = Field(default=30, ge=2)
    cv_threshold: float = Field(default=10.0, gt=0)


class PredictionTheoryParams(BaseModel):
    """Required params for prediction-pillar theories."""
    # critical_power theory has distance_power_fractions; riegel has riegel_exponent
    riegel_exponent: float = 1.06
    threshold_reference_km: float = 10.0
    distance_power_fractions: dict[str, float] | None = None


class ZoneTheoryParams(BaseModel):
    """Required params for zone-pillar theories (e.g., coggan_5zone)."""
    zone_count: int
    boundaries: dict[str, list[float]]
    zone_names: list[str] | dict[str, list[str]]
    target_distribution: list[float]

    @model_validator(mode="after")
    def check_zone_configuration(self) -> "ZoneTheoryParams":
        """Validate boundary and target-distribution cardinality and ranges."""
        expected_boundaries = self.zone_count - 1
        for base, bounds in self.boundaries.items():
            if len(bounds) != expected_boundaries:
                raise ValueError(
                    f"boundaries[{base}] has {len(bounds)} values, "
                    f"expected {expected_boundaries} (zone_count={self.zone_count})"
                )
        if len(self.target_distribution) != self.zone_count:
            raise ValueError(
                "target_distribution must contain one value per zone "
                f"(expected {self.zone_count})"
            )
        if any(value < 0 or value > 1 for value in self.target_distribution):
            raise ValueError("target_distribution values must be between 0 and 1")
        if abs(sum(self.target_distribution) - 1.0) > 1e-6:
            raise ValueError("target_distribution values must sum to 1.0")
        return self


class SignalParams(BaseModel):
    """Optional signal thresholds used by load/recovery theories."""
    readiness_rest: float = 60
    readiness_modify: float = 70
    tsb_high_fatigue: float = -20
    hrv_decline_pct: float = -15


class DiagnosisParams(BaseModel):
    """Optional diagnosis parameters used by load theories."""
    work_split_min_sec: int = Field(default=120, gt=0)
    work_split_max_sec: int = Field(default=1800, gt=0)
    volume_strong_km: float = Field(default=60, gt=0)
    volume_moderate_km: float = Field(default=40, gt=0)

    @model_validator(mode="after")
    def check_ranges(self) -> "DiagnosisParams":
        """Ensure duration and volume bands are ordered."""
        if self.work_split_max_sec < self.work_split_min_sec:
            raise ValueError("work_split_max_sec must be >= work_split_min_sec")
        if self.volume_strong_km < self.volume_moderate_km:
            raise ValueError("volume_strong_km must be >= volume_moderate_km")
        return self


# Map pillar name -> params validator class
PILLAR_PARAMS_SCHEMA: dict[str, type[BaseModel]] = {
    "load": LoadTheoryParams,
    "recovery": RecoveryTheoryParams,
    "prediction": PredictionTheoryParams,
    "zones": ZoneTheoryParams,
}


def validate_theory_params(pillar: str, params: dict[str, Any]) -> dict[str, Any]:
    """Validate theory params against the pillar-specific schema.

    Returns the validated (and potentially defaulted) params dict.
    Raises pydantic.ValidationError if required fields are missing or wrong type.
    """
    schema_cls = PILLAR_PARAMS_SCHEMA.get(pillar)
    if schema_cls is None:
        return params
    validated = schema_cls.model_validate(params)
    return validated.model_dump()


def validate_signal_params(signal: dict[str, Any]) -> dict[str, Any]:
    """Validate signal params if present."""
    if not signal:
        return signal
    validated = SignalParams.model_validate(signal)
    return validated.model_dump()


def validate_diagnosis_params(diagnosis: dict[str, Any]) -> dict[str, Any]:
    """Validate diagnosis params if present."""
    if not diagnosis:
        return diagnosis
    validated = DiagnosisParams.model_validate(diagnosis)
    return validated.model_dump()
