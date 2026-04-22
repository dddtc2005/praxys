"""Regression tests for per-training-base plan load estimation.

Historical bug: ``_estimate_plan_daily_loads`` and the planned half of
``_build_compliance`` only looked at ``target_power_*`` columns, so HR-base
and pace-base plans defaulted every workout to a flat ~60 RSS/hour. The
projected fitness-fatigue curve and compliance chart both used the wrong
number, and the weekly "planned" bar collapsed to a generic value.
"""
from datetime import date, timedelta

import pandas as pd

from analysis.providers.models import ThresholdEstimate
from api.deps import (
    _estimate_plan_daily_loads,
    _parse_pace_str,
    _plan_workout_load,
    _has_base_targets,
)


def _mk_plan_row(**overrides):
    base = {
        "date": date(2026, 4, 23),
        "planned_duration_min": 60.0,
        "target_power_min": None,
        "target_power_max": None,
        "target_hr_min": None,
        "target_hr_max": None,
        "target_pace_min": None,
        "target_pace_max": None,
    }
    base.update(overrides)
    return pd.Series(base)


def test_parse_pace_str_handles_common_formats():
    assert _parse_pace_str("4:30") == 270.0
    assert _parse_pace_str("5:00") == 300.0
    assert _parse_pace_str("4:30/km") == 270.0
    assert _parse_pace_str("4:30 min/km") == 270.0
    assert _parse_pace_str("") is None
    assert _parse_pace_str(None) is None
    # Bare number interpreted as sec/km.
    assert _parse_pace_str("270") == 270.0
    assert _parse_pace_str(280.5) == 280.5


def test_power_plan_uses_rss_formula():
    thresholds = ThresholdEstimate()
    thresholds.cp_watts = 260.0
    row = _mk_plan_row(target_power_min=210, target_power_max=230)
    load = _plan_workout_load(row, 3600.0, "power", thresholds)
    # RSS = 1h * (220/260)^2 * 100 ≈ 71.6
    assert 65 < load < 80, f"power plan should produce RSS-shaped load, got {load}"


def test_hr_plan_uses_trimp_formula():
    thresholds = ThresholdEstimate()
    thresholds.max_hr_bpm = 185.0
    thresholds.rest_hr_bpm = 50.0
    row = _mk_plan_row(target_hr_min=140, target_hr_max=160)
    load = _plan_workout_load(row, 3600.0, "hr", thresholds)
    # 60 min at avg HR 150 → delta_ratio = 100/135 = 0.7407 → Banister
    # TRIMP = 60 × 0.7407 × 0.64 × exp(1.92 × 0.7407) ≈ 117.9. Narrow 110–125
    # window pins the formula; the 60/hr flat fallback (the regression we
    # care about) cannot reach 110.
    assert 110 < load < 125, f"HR plan should produce ~118 TRIMP, got {load:.1f}"


def test_pace_plan_uses_rtss_formula():
    thresholds = ThresholdEstimate()
    thresholds.threshold_pace_sec_km = 260.0  # 4:20/km threshold
    row = _mk_plan_row(target_pace_min="4:30", target_pace_max="5:00")
    load = _plan_workout_load(row, 3600.0, "pace", thresholds)
    # 60-min run at ~4:45/km average (285 sec/km) vs threshold 260:
    # intensity = 260/285 ≈ 0.912 → rTSS ≈ 83.2
    assert 70 < load < 95, f"pace plan should produce rTSS-shaped load, got {load}"


def test_hr_plan_without_targets_falls_back_to_flat_rate():
    """A plan row with no HR targets can't compute TRIMP — fall back to a flat rate."""
    thresholds = ThresholdEstimate()
    thresholds.max_hr_bpm = 185.0
    row = _mk_plan_row()  # no targets at all
    load = _plan_workout_load(row, 3600.0, "hr", thresholds)
    assert abs(load - 60.0) < 0.001, "expected the 60 units/hour fallback for untargeted rows"


def test_estimate_plan_daily_loads_hr_base():
    """Full daily-load loop for an HR-base user over a 3-day window."""
    thresholds = ThresholdEstimate()
    thresholds.max_hr_bpm = 185.0
    thresholds.rest_hr_bpm = 50.0

    start = date(2026, 4, 22)
    plan = pd.DataFrame([
        # Day 1 — hard HR workout
        {"date": start + timedelta(days=1), "planned_duration_min": 60.0,
         "target_hr_min": 170.0, "target_hr_max": 180.0},
        # Day 2 — no workout
        # Day 3 — easy HR workout
        {"date": start + timedelta(days=3), "planned_duration_min": 45.0,
         "target_hr_min": 120.0, "target_hr_max": 135.0},
    ])
    loads = _estimate_plan_daily_loads(plan, start, days=3, thresholds=thresholds, training_base="hr")
    assert len(loads) == 3
    assert loads[0] > loads[2] > 0, "hard day must beat easy day, both non-zero"
    assert loads[1] == 0.0, "rest day stays at zero"


def test_has_base_targets_detects_missing_data():
    assert _has_base_targets(_mk_plan_row(target_power_min=200), "power") is True
    assert _has_base_targets(_mk_plan_row(), "power") is False
    assert _has_base_targets(_mk_plan_row(target_hr_max=160), "hr") is True
    assert _has_base_targets(_mk_plan_row(), "hr") is False
    assert _has_base_targets(_mk_plan_row(target_pace_max="5:00"), "pace") is True
    assert _has_base_targets(_mk_plan_row(), "pace") is False
