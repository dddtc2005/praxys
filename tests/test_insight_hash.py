"""Tests for the per-insight-type dataset fingerprinting in
``analysis/insight_hash.py``.
"""
from __future__ import annotations

import pytest

from analysis.insight_hash import build_training_review_inputs, compute_dataset_hash


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
                {"date": "2026-04-21", "distance_km": 8.0, "rss": 60.0, "avg_power": 200, "duration_min": 45},
                {"date": "2026-04-23", "distance_km": 12.0, "rss": 95.0, "avg_power": 230, "duration_min": 70},
            ],
            "diagnosis": {
                "distribution": [{"name": "Endurance", "actual_pct": 80}],
                "interval_power": {"max": 300, "evidence_complete": True},
                "data_meta": {"distribution_complete": True},
            },
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


def test_target_time_change_affects_race_forecast_and_daily_brief():
    ctx_a = _ctx_race()
    ctx_b = _ctx_race()
    ctx_b["athlete_profile"]["goal"]["target_time_sec"] = 9900

    assert compute_dataset_hash(
        ctx_a, "race_forecast", science_pillars=PILLARS,
    ) != compute_dataset_hash(
        ctx_b, "race_forecast", science_pillars=PILLARS,
    )
    assert compute_dataset_hash(
        ctx_a, "daily_brief", science_pillars=PILLARS,
    ) != compute_dataset_hash(
        ctx_b, "daily_brief", science_pillars=PILLARS,
    )


def test_race_countdown_change_invalidates_daily_brief_hash():
    ctx_a = _ctx_daily()
    ctx_b = _ctx_daily()
    ctx_a["current_fitness"]["race_countdown"] = {"days_remaining": 8}
    ctx_b["current_fitness"]["race_countdown"] = {"days_remaining": 7}

    assert compute_dataset_hash(
        ctx_a, "daily_brief", science_pillars=PILLARS,
    ) != compute_dataset_hash(
        ctx_b, "daily_brief", science_pillars=PILLARS,
    )

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


def test_review_activity_average_power_does_not_change_hash():
    ctx_a = _ctx_review()
    ctx_b = _ctx_review()
    ctx_b["recent_training"]["sessions"][0]["avg_power"] = 400
    assert compute_dataset_hash(ctx_a, "training_review", science_pillars=PILLARS) == \
           compute_dataset_hash(ctx_b, "training_review", science_pillars=PILLARS)


def test_review_split_diagnosis_change_invalidates_hash():
    ctx_a = _ctx_review()
    ctx_b = _ctx_review()
    ctx_b["recent_training"]["diagnosis"]["distribution"][0]["actual_pct"] = 60
    assert compute_dataset_hash(ctx_a, "training_review", science_pillars=PILLARS) != \
           compute_dataset_hash(ctx_b, "training_review", science_pillars=PILLARS)


def test_review_volume_chart_arrays_do_not_churn_model_inputs():
    """Rolling chart labels are not independent training-review evidence."""
    ctx_a = _ctx_review()
    ctx_b = _ctx_review()
    ctx_a["recent_training"]["diagnosis"]["volume"] = {
        "weekly_avg_km": 40.0,
        "trend": "stable",
        "weeks": ["2026-04-14", "2026-04-21"],
        "weekly_km": [40.0, 40.0],
    }
    ctx_b["recent_training"]["diagnosis"]["volume"] = {
        "weekly_avg_km": 40.0,
        "trend": "stable",
        "weeks": ["2026-04-15", "2026-04-22"],
        "weekly_km": [39.0, 41.0],
    }

    payload = build_training_review_inputs(ctx_a)

    assert payload["split_level_diagnosis"]["volume"] == {
        "weekly_avg_km": 40.0,
        "trend": "stable",
    }
    assert compute_dataset_hash(
        ctx_a,
        "training_review",
        science_pillars=PILLARS,
    ) == compute_dataset_hash(
        ctx_b,
        "training_review",
        science_pillars=PILLARS,
    )


def test_partial_distribution_placeholders_do_not_change_review_hash():
    """Unavailable display placeholders are excluded from the model identity."""
    ctx_a = _ctx_review()
    ctx_b = _ctx_review()
    for context in (ctx_a, ctx_b):
        context["recent_training"]["diagnosis"]["data_meta"] = {
            "distribution_complete": False,
            "distribution_coverage_pct": 30,
        }
        context["science"] = {
            "zones": {
                "zone_names": ["Easy", "Hard"],
                "target_distribution": [0.8, 0.2],
            },
        }
    ctx_b["recent_training"]["diagnosis"]["distribution"] = [
        {"name": "Easy", "actual_pct": 0, "target_pct": 10},
    ]
    ctx_b["science"]["zones"]["zone_names"] = ["Low", "High"]
    ctx_b["science"]["zones"]["target_distribution"] = [0.1, 0.9]

    assert compute_dataset_hash(
        ctx_a, "training_review", science_pillars=PILLARS,
    ) == compute_dataset_hash(
        ctx_b, "training_review", science_pillars=PILLARS,
    )

def test_incomplete_interval_values_are_removed_from_review_inputs():
    """Partial interval evidence cannot affect or enter the model payload."""
    context = _ctx_review()
    context["recent_training"]["diagnosis"]["interval_power"] = {
        "max": 400,
        "avg": 350,
        "evidence_complete": False,
    }

    payload = build_training_review_inputs(context)

    assert "interval_power" not in payload["split_level_diagnosis"]


def test_review_prompt_session_change_invalidates_hash():
    ctx_a = _ctx_review()
    ctx_b = _ctx_review()
    ctx_b["recent_training"]["sessions"][0]["duration_min"] = 60
    assert compute_dataset_hash(ctx_a, "training_review", science_pillars=PILLARS) != \
           compute_dataset_hash(ctx_b, "training_review", science_pillars=PILLARS)


# ---------------------------------------------------------------------------
# daily_brief: planned_today, not current_plan[0]
# ---------------------------------------------------------------------------


def test_daily_brief_hash_keys_off_planned_today_not_current_plan():
    """When today is rest, the hash must not entangle with whichever
    future workout happens to be next in the plan. Otherwise a plan
    tweak two weeks out would burn an LLM regen for today's brief."""
    base = _ctx_daily()
    base["planned_today"] = None
    base["current_plan"] = [
        {"workout_type": "easy", "planned_duration_min": 45,
         "target_power_min": 180, "target_power_max": 210},
    ]
    h_a = compute_dataset_hash(base, "daily_brief", science_pillars=PILLARS)

    # Future workout swap — today is still rest. Hash must not change.
    swapped = {**base, "current_plan": [
        {"workout_type": "threshold", "planned_duration_min": 90,
         "target_power_min": 240, "target_power_max": 280},
    ]}
    h_b = compute_dataset_hash(swapped, "daily_brief", science_pillars=PILLARS)
    assert h_a == h_b


def test_daily_brief_hash_changes_when_planned_today_changes():
    """When today's plan slot itself changes (rest → easy run, or workout
    type swap), the hash MUST change so the runner regenerates the brief."""
    rest = _ctx_daily()
    rest["planned_today"] = None
    rest["current_plan"] = []
    h_rest = compute_dataset_hash(rest, "daily_brief", science_pillars=PILLARS)

    easy = _ctx_daily()
    easy["planned_today"] = {
        "workout_type": "easy", "planned_duration_min": 45,
        "target_power_min": 180, "target_power_max": 210,
    }
    easy["current_plan"] = [easy["planned_today"]]
    h_easy = compute_dataset_hash(easy, "daily_brief", science_pillars=PILLARS)
    assert h_rest != h_easy

    threshold = {**easy, "planned_today": {
        "workout_type": "threshold", "planned_duration_min": 60,
        "target_power_min": 240, "target_power_max": 280,
    }}
    h_threshold = compute_dataset_hash(threshold, "daily_brief", science_pillars=PILLARS)
    assert h_easy != h_threshold


@pytest.mark.parametrize(
    ("field", "before", "after"),
    [
        ("start_time", "2026-07-12T06:00:00Z", "2026-07-12T18:00:00Z"),
        ("planned_duration_min", 41, 44),
        ("planned_distance_km", 8.1, 8.4),
        ("target_power_min", 251, 259),
        ("target_power_max", 271, 279),
        ("target_hr_min", 151, 154),
        ("target_hr_max", 150, 180),
        ("target_pace_min", "5:20/km", "4:50/km"),
        ("target_pace_max", "5:40/km", "5:10/km"),
        (
            "workout_description",
            "Easy aerobic run",
            "Threshold intervals: 4 x 8 minutes",
        ),
    ],
)
def test_daily_brief_hash_changes_with_material_workout_detail(
    field, before, after,
):
    """Every workout detail sent to the LLM must invalidate stale prose."""
    ctx_a = _ctx_daily()
    ctx_b = _ctx_daily()
    ctx_a["planned_today"] = {"workout_type": "easy", field: before}
    ctx_b["planned_today"] = {"workout_type": "easy", field: after}

    assert compute_dataset_hash(
        ctx_a, "daily_brief", science_pillars=PILLARS,
    ) != compute_dataset_hash(
        ctx_b, "daily_brief", science_pillars=PILLARS,
    )


def test_daily_brief_hash_changes_when_today_signal_changes():
    """Canonical Today-verdict changes must invalidate the cached daily brief."""
    rest = _ctx_daily(today_signal={
        "recommendation": "rest",
        "reason": "Recovery first.",
        "alternatives": ["Walk only"],
    })
    follow_plan = _ctx_daily(today_signal={
        "recommendation": "follow_plan",
        "reason": "Recovered.",
        "alternatives": [],
    })

    assert compute_dataset_hash(rest, "daily_brief", science_pillars=PILLARS) != \
           compute_dataset_hash(follow_plan, "daily_brief", science_pillars=PILLARS)
