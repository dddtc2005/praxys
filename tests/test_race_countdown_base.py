"""Regression tests for _build_race_countdown per training base.

Historical bug: an HR-base user's LTHR (bpm) was passed as ``latest_cp``
into power formulas, yielding a nonsensical "172 → 235 bpm" target on the
Goal page and an absurd race prediction. Every case here exercises one
(training_base, has_cp_watts, has_threshold_pace) combination to pin the
dispatch down.
"""
from datetime import date

from api.deps import _build_race_countdown, _select_prediction_method


_TODAY = date(2026, 4, 22)
_TREND = {"direction": "rising", "slope_per_month": 0.5}
# Pairs roughly match a 4:30/km runner at 230W.
_POWER_PACE_PAIRS = [(230.0, 270.0), (235.0, 265.0), (225.0, 275.0)]


def _call(
    *,
    training_base: str,
    latest_threshold: float | None,
    latest_cp_watts: float | None,
    threshold_pace: float | None = None,
    target_time_sec: int | None = 10_800,  # 3:00 marathon
    race_date_str: str = "",
    prediction_method: str | None = "critical_power",
) -> dict:
    return _build_race_countdown(
        race_date_str=race_date_str,
        target_time_sec=target_time_sec,
        latest_threshold=latest_threshold,
        latest_cp_watts=latest_cp_watts,
        power_pace_pairs=_POWER_PACE_PAIRS,
        cp_trend_data=_TREND,
        today=_TODAY,
        training_base=training_base,
        threshold_pace=threshold_pace,
        prediction_method=prediction_method,
    )


def test_hr_base_with_target_has_no_cp_target():
    """LTHR is not a trainable race-pace target — never surface a ``target_cp``."""
    result = _call(
        training_base="hr",
        latest_threshold=172.0,   # LTHR in bpm
        latest_cp_watts=None,     # HR user has no CP watts
        threshold_pace=None,
        prediction_method=None,
    )
    assert result["mode"] == "cp_milestone"
    assert result["current_cp"] is None, "HR user has no trainable threshold target"
    assert result["target_cp"] is None, "must never render an LTHR target — no such formula exists"


def test_hr_base_never_feeds_lthr_into_power_formula():
    """Even if prediction_method resolves to critical_power (e.g. because a
    Garmin-native FTP is present), an HR-base user's LTHR must not be used
    as the watts input. ``latest_cp_watts`` is the only path for that.
    """
    # HR user whose Garmin also wrote a native FTP: latest_cp_watts=260.
    # Their LTHR is 172 bpm. The prediction uses CP watts; the display uses
    # LTHR. They must stay in separate lanes.
    result = _call(
        training_base="hr",
        latest_threshold=172.0,
        latest_cp_watts=260.0,
        threshold_pace=None,
        prediction_method="critical_power",
    )
    assert result["target_cp"] is None, "HR base: no target_cp regardless of CP availability"
    # Prediction used CP watts, not the LTHR. For avg_k across our fixture
    # pairs ≈ 62083 and the function's default power_fraction=0.80, predicted
    # pace ≈ 62083 / (260 × 0.80) ≈ 298 sec/km → marathon ≈ 298 × 42.195
    # ≈ 12_582 s ≈ 3:30. A 3:15–3:45 window pins this path while rejecting
    # both the 4:50 regression (treating 172 bpm as watts → ~4:49) and the
    # 2:22 regression (overshooting CP via wrong-source pairs → ~2:22).
    t = result["predicted_time_sec"]
    assert t is not None
    assert 3 * 3600 + 15 * 60 < t < 3 * 3600 + 45 * 60, (
        f"expected ~3:30 from 260W path, got {t/3600:.2f}h — the 4:50 regression "
        f"(treating 172 bpm as watts) or the 2:22 regression (overshooting CP) "
        f"would both fall outside this window"
    )


def test_hr_base_falls_back_to_riegel_when_only_pace_available():
    """HR user with no CP watts but a threshold pace — use Riegel."""
    result = _call(
        training_base="hr",
        latest_threshold=172.0,
        latest_cp_watts=None,
        threshold_pace=280.0,  # ~4:40/km threshold
        prediction_method="riegel",
    )
    assert result["prediction_method"] == "riegel"
    assert result["predicted_time_sec"] is not None
    # Riegel from 4:40/km threshold → marathon well over 3:00 but under 5:00.
    assert 3 * 3600 < result["predicted_time_sec"] < 5 * 3600
    assert result["target_cp"] is None


def test_power_base_with_cp_produces_watts_target():
    """Power user: target_cp is in watts, computed from power-pace inversion."""
    result = _call(
        training_base="power",
        latest_threshold=260.0,    # CP in watts
        latest_cp_watts=260.0,
        threshold_pace=None,
        prediction_method="critical_power",
    )
    assert result["mode"] == "cp_milestone"
    assert result["current_cp"] == 260.0
    assert result["target_cp"] is not None
    # For a 3:00 marathon target, required CP must exceed current (else user
    # would already be on pace). Sanity-check the unit is watts, not bpm.
    assert 150 < result["target_cp"] < 500, "target_cp must be a plausible watts value"


def test_pace_base_with_threshold_pace_produces_pace_target():
    """Pace user: target is a threshold pace in sec/km (inverse Riegel)."""
    result = _call(
        training_base="pace",
        latest_threshold=280.0,    # LT pace sec/km
        latest_cp_watts=None,
        threshold_pace=280.0,
        prediction_method="riegel",
    )
    assert result["mode"] == "cp_milestone"
    assert result["current_cp"] == 280.0
    assert result["target_cp"] is not None
    # For a 3:00 marathon target the needed threshold pace is well under 280 sec/km.
    assert 150 < result["target_cp"] < 280


def test_continuous_mode_shows_base_native_threshold():
    """No target time — ``current_cp`` is the base-native value (bpm for HR)."""
    result = _call(
        training_base="hr",
        latest_threshold=172.0,
        latest_cp_watts=None,
        threshold_pace=None,
        target_time_sec=None,
        prediction_method=None,
    )
    assert result["mode"] == "continuous"
    assert result["current_cp"] == 172.0, (
        "continuous mode must expose the base-native display value (LTHR 172 bpm)"
    )


def test_select_prediction_method_hr_user_with_garmin_ftp_only():
    """Regression for the 2:22 marathon bug.

    HR user whose config picked no pace test but whose Garmin wrote a
    native FTP (``has_cp=True``). Even with the default ``critical_power``
    science theory, we must NOT select the CP model — pairing inflated
    Garmin FTP with Stryd-via-CIQ activity power produces garbage.
    """
    assert _select_prediction_method(
        "hr",
        "critical_power",
        has_cp=True,
        has_pace=False,
    ) is None
    # And with a pace measurement, Riegel should win over CP.
    assert _select_prediction_method(
        "hr",
        "critical_power",
        has_cp=True,
        has_pace=True,
    ) == "riegel"


def test_select_prediction_method_power_user_default():
    """Power user with CP available: default is the CP model."""
    assert _select_prediction_method(
        "power",
        "critical_power",
        has_cp=True,
        has_pace=False,
    ) == "critical_power"


def test_select_prediction_method_power_user_explicit_riegel():
    """Power user who explicitly picked Riegel honors that choice when pace is available."""
    assert _select_prediction_method(
        "power",
        "riegel",
        has_cp=True,
        has_pace=True,
    ) == "riegel"
    # But if the pace data is missing, Riegel can't run — fall back to CP.
    assert _select_prediction_method(
        "power",
        "riegel",
        has_cp=True,
        has_pace=False,
    ) == "critical_power"


def test_select_prediction_method_pace_user_always_riegel():
    """Pace user: always Riegel, never CP."""
    assert _select_prediction_method(
        "pace",
        "critical_power",
        has_cp=True,
        has_pace=True,
    ) == "riegel"
    # No pace data → no prediction.
    assert _select_prediction_method(
        "pace",
        "critical_power",
        has_cp=True,
        has_pace=False,
    ) is None


def test_race_date_mode_hr_base_has_no_reality_check_threshold():
    """With a race date set, HR users still have no meaningful needed-threshold."""
    result = _call(
        training_base="hr",
        latest_threshold=172.0,
        latest_cp_watts=None,
        threshold_pace=280.0,
        race_date_str="2026-06-01",
        prediction_method="riegel",
    )
    assert result["mode"] == "race_date"
    # race_honesty_check returns "Insufficient data" when current is None,
    # which is what we want for HR users — no pretend target.
    reality = result["reality_check"]
    assert "needed_cp" not in reality or reality.get("needed_cp") is None
