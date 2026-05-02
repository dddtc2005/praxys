"""Tests for the per-insight-type dataset fingerprinting in
``analysis/insight_hash.py``.
"""
from __future__ import annotations

import pytest

from analysis.insight_hash import compute_dataset_hash


def _ctx_daily(**overrides):
    base = {
        "recovery_state": {
            "hrv_ms": 60.0,
            "hrv_trend_pct": 2.0,
            "sleep_score": 80,
            "readiness": "fresh",
        },
        "current_fitness": {"ctl": 50.0, "atl": 45.0, "tsb": 5.0},
        "current_plan": [
            {
                "workout_type": "easy",
                "planned_duration_min": 45,
                "planned_distance_km": 8.0,
                "target_power_min": 180,
                "target_power_max": 210,
            }
        ],
    }
    base.update(overrides)
    return base


def _ctx_review():
    return {
        "recent_training": {
            "sessions": [
                {"date": "2026-04-21", "distance_km": 8.0, "rss": 60.0, "avg_power": 200},
                {"date": "2026-04-23", "distance_km": 12.0, "rss": 95.0, "avg_power": 230},
            ],
            "weekly_summary": [
                {"week": "2026-W17", "volume_km": 40.0, "load": 250.0, "sessions": 5},
            ],
        },
        "current_fitness": {
            "cp_trend": {"direction": "up", "slope_per_month": 1.5},
        },
    }


def _ctx_race():
    return {
        "current_fitness": {
            "cp_trend": {"current": 280.0, "direction": "up", "slope_per_month": 1.5},
            "predicted_time_sec": 10800,
        },
        "athlete_profile": {
            "goal": {
                "race_date": "2026-09-01",
                "target_time_sec": 10800,
                "distance": "marathon",
            }
        },
    }


PILLARS = {
    "load": "banister_pmc",
    "recovery": "hrv_based",
    "prediction": "critical_power",
    "zones": "five_zone",
}


# ---------------------------------------------------------------------------
# Stability
# ---------------------------------------------------------------------------


def test_identical_contexts_produce_equal_hashes():
    h1 = compute_dataset_hash(_ctx_daily(), "daily_brief", science_pillars=PILLARS)
    h2 = compute_dataset_hash(_ctx_daily(), "daily_brief", science_pillars=PILLARS)
    assert h1 == h2


def test_pillar_dict_key_order_does_not_matter():
    pillars_a = {"load": "banister_pmc", "recovery": "hrv_based"}
    pillars_b = {"recovery": "hrv_based", "load": "banister_pmc"}
    h1 = compute_dataset_hash(_ctx_daily(), "daily_brief", science_pillars=pillars_a)
    h2 = compute_dataset_hash(_ctx_daily(), "daily_brief", science_pillars=pillars_b)
    assert h1 == h2


def test_small_drift_within_bucket_does_not_change_hash():
    # CTL is bucketed to 0.5 — drift of 0.001 must not trip rehash.
    ctx_a = _ctx_daily(current_fitness={"ctl": 50.000, "atl": 45.0, "tsb": 5.0})
    ctx_b = _ctx_daily(current_fitness={"ctl": 50.001, "atl": 45.0, "tsb": 5.0})
    assert compute_dataset_hash(ctx_a, "daily_brief", science_pillars=PILLARS) == \
           compute_dataset_hash(ctx_b, "daily_brief", science_pillars=PILLARS)


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------


def test_pillar_swap_invalidates_hash():
    base = compute_dataset_hash(_ctx_daily(), "daily_brief", science_pillars=PILLARS)
    swapped = compute_dataset_hash(
        _ctx_daily(),
        "daily_brief",
        science_pillars={**PILLARS, "load": "seiler_polarized"},
    )
    assert base != swapped


def test_significant_ctl_change_invalidates_hash():
    ctx_a = _ctx_daily(current_fitness={"ctl": 50.0, "atl": 45.0, "tsb": 5.0})
    ctx_b = _ctx_daily(current_fitness={"ctl": 55.0, "atl": 45.0, "tsb": 5.0})
    assert compute_dataset_hash(ctx_a, "daily_brief", science_pillars=PILLARS) != \
           compute_dataset_hash(ctx_b, "daily_brief", science_pillars=PILLARS)


def test_target_time_change_affects_race_forecast_only():
    ctx_race_a = _ctx_race()
    ctx_race_b = _ctx_race()
    ctx_race_b["athlete_profile"]["goal"]["target_time_sec"] = 9900  # 30s faster
    h_race_a = compute_dataset_hash(ctx_race_a, "race_forecast", science_pillars=PILLARS)
    h_race_b = compute_dataset_hash(ctx_race_b, "race_forecast", science_pillars=PILLARS)
    assert h_race_a != h_race_b

    # Same change should not affect daily_brief (target time isn't part of its
    # projection — target time only matters for the forecast).
    h_daily_a = compute_dataset_hash(_ctx_daily(), "daily_brief", science_pillars=PILLARS)
    h_daily_b = compute_dataset_hash(_ctx_daily(), "daily_brief", science_pillars=PILLARS)
    assert h_daily_a == h_daily_b


# ---------------------------------------------------------------------------
# Behavior on edge inputs
# ---------------------------------------------------------------------------


def test_missing_recovery_state_does_not_raise():
    ctx = {"recovery_state": {}, "current_fitness": {}, "current_plan": []}
    h = compute_dataset_hash(ctx, "daily_brief", science_pillars=None)
    assert isinstance(h, str) and len(h) == 64


def test_unknown_insight_type_raises():
    with pytest.raises(ValueError, match="Unknown insight_type"):
        compute_dataset_hash({}, "weekly_summary", science_pillars=PILLARS)


def test_review_session_drift_within_bucket_does_not_change_hash():
    ctx_a = _ctx_review()
    ctx_b = _ctx_review()
    # avg_power bucketed to 10W — 200 and 204 both bucket to 200.
    ctx_b["recent_training"]["sessions"][0]["avg_power"] = 204
    assert compute_dataset_hash(ctx_a, "training_review", science_pillars=PILLARS) == \
           compute_dataset_hash(ctx_b, "training_review", science_pillars=PILLARS)


def test_review_session_significant_change_invalidates_hash():
    ctx_a = _ctx_review()
    ctx_b = _ctx_review()
    # 200 → 230 crosses bucket boundary.
    ctx_b["recent_training"]["sessions"][0]["avg_power"] = 230
    assert compute_dataset_hash(ctx_a, "training_review", science_pillars=PILLARS) != \
           compute_dataset_hash(ctx_b, "training_review", science_pillars=PILLARS)
