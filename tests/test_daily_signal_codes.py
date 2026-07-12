"""Contract tests for every deterministic Today guidance code."""

import pytest

from analysis.metrics import daily_training_signal


def _recovery(
    status: str = "normal",
    *,
    trend: str = "stable",
    cv: float = 5.0,
    sleep: float | None = 80.0,
    rhr_trend: str | None = "stable",
    classification_reason: str | None = None,
    stale: bool = False,
) -> dict:
    hrv = None if status == "insufficient_data" else {
        "today_ms": 50.0,
        "today_ln": 3.91,
        "baseline_mean_ln": 3.90,
        "baseline_sd_ln": 0.10,
        "threshold_ln": 3.75,
        "swc_upper_ln": 4.05,
        "rolling_mean_ln": 3.90,
        "rolling_cv": cv,
        "trend": trend,
    }
    return {
        "status": status,
        "hrv": hrv,
        "sleep_score": sleep,
        "readiness_score": None,
        "resting_hr": 52.0,
        "rhr_trend": rhr_trend,
        "classification_reason": classification_reason,
        "hrv_is_stale": stale,
    }


@pytest.mark.parametrize(
    ("recovery", "tsb", "workout", "expected_reason", "expected_alternatives"),
    [
        (_recovery("fatigued"), -5, "", "unscheduled_hrv_caution", ["restorative_movement"]),
        (_recovery(), -25, "", "unscheduled_high_load", ["optional_easy_short"]),
        (_recovery(), 0, "", "unscheduled_open", []),
        (_recovery(), 0, "rest", "rest_scheduled", []),
        (_recovery("insufficient_data", stale=True), 0, "easy", "hrv_stale", []),
        (_recovery("insufficient_data", classification_reason="zero_variance"), 0, "easy", "hrv_zero_variance", []),
        (_recovery("insufficient_data", classification_reason="insufficient_history"), 0, "easy", "hrv_history_insufficient", []),
        (_recovery("insufficient_data", classification_reason="missing_hrv"), 0, "easy", "hrv_unavailable", []),
        (_recovery("fatigued"), 0, "threshold", "hrv_below_hard", ["full_recovery_reassess"]),
        (_recovery("fatigued"), 0, "easy", "hrv_below_easy", []),
        (_recovery(), -25, "threshold", "high_load_hard", ["drop_to_easy", "push_to_tomorrow_if_easy", "cap_low_power"]),
        (_recovery(trend="declining"), 0, "threshold", "hrv_declining_hard", ["swap_for_easy"]),
        (_recovery(trend="declining"), 0, "easy", "hrv_declining_easy", []),
        (_recovery(cv=15), 0, "threshold", "hrv_variability_high", ["drop_one_zone", "push_to_tomorrow"]),
        (_recovery(sleep=40), 0, "threshold", "sleep_low_hard", ["proceed_monitor_body", "shorten_if_fatigued"]),
        (_recovery(rhr_trend="elevated"), 0, "threshold", "resting_hr_elevated_hard", ["run_easy", "monitor_hr_drift"]),
        (_recovery("fresh"), 0, "easy", "hrv_above_baseline", []),
        (_recovery(), 0, "easy", "recovery_normal", []),
    ],
)
def test_daily_signal_semantic_codes(
    recovery: dict,
    tsb: float,
    workout: str,
    expected_reason: str,
    expected_alternatives: list[str],
) -> None:
    """Every decision path exposes stable client-localization codes."""
    signal = daily_training_signal(recovery, tsb, workout)

    assert signal["reason_code"] == expected_reason
    assert [item["code"] for item in signal["alternative_codes"]] == expected_alternatives
    assert len(signal["alternatives"]) == len(expected_alternatives)