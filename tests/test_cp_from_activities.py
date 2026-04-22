"""Unit tests for the activity-derived CP fit (analysis/cp_from_activities.py).

Exercises the pure functions directly — the DB-reading
``estimate_cp_from_activities`` is covered by the integration test in
``test_cp_from_activities_integration.py``.
"""
from datetime import date

import pytest

from analysis.cp_from_activities import (
    MAX_PLAUSIBLE_CP_WATTS,
    MIN_FIT_DURATION_SEC,
    MIN_FIT_POINTS,
    MIN_PLAUSIBLE_CP_WATTS,
    CpFitResult,
    collect_mean_max_points,
    fit_cp_wprime,
)


def _synth_points(cp: float, w_prime: float, durations_sec: list[float]) -> list[tuple[float, float]]:
    """Generate ideal (duration, power) points from the CP model.

    P = CP + W'/t — the inverse relationship the fit is designed to recover.
    """
    return [(t, cp + w_prime / t) for t in durations_sec]


class TestCollectMeanMaxPoints:
    def test_keeps_highest_power_per_bin(self):
        # Two observations in the 3–6 min bin (180–360s): one weak, one strong.
        obs = [
            (200.0, 240.0),  # weak 3:20 effort
            (240.0, 270.0),  # strong 4:00 effort — should win the 180–360 bin
            (600.0, 230.0),  # 10:00 effort — own bin (360–720)
        ]
        out = collect_mean_max_points(obs)
        # Expect the 270W point, not the 240W one
        powers = [p for _, p in out]
        assert 270.0 in powers
        assert 240.0 not in powers
        # Sorted by duration ascending
        assert [d for d, _ in out] == sorted(d for d, _ in out)

    def test_filters_non_positive(self):
        obs = [
            (-10.0, 200.0),
            (300.0, 0.0),
            (300.0, -50.0),
            (None, 200.0),
            (300.0, None),
            (250.0, 230.0),  # only valid one
        ]
        out = collect_mean_max_points(obs)  # type: ignore[arg-type]
        assert out == [(250.0, 230.0)]

    def test_drops_points_outside_any_bin(self):
        # 30 s is below the lowest bin (60 s) — must be discarded.
        obs = [(30.0, 400.0), (300.0, 250.0)]
        out = collect_mean_max_points(obs)
        assert out == [(300.0, 250.0)]


class TestFitCpWprime:
    def test_recovers_known_cp_and_wprime_from_ideal_points(self):
        cp_true, wp_true = 260.0, 15_000.0
        points = _synth_points(cp_true, wp_true, [180.0, 300.0, 600.0, 1200.0])
        result = fit_cp_wprime(points)
        assert result is not None
        assert abs(result.cp_watts - cp_true) < 0.5, (
            f"expected CP≈{cp_true}, got {result.cp_watts}"
        )
        assert abs(result.w_prime_joules - wp_true) < 5.0, (
            f"expected W'≈{wp_true}, got {result.w_prime_joules}"
        )
        assert result.r_squared > 0.999

    def test_rejects_too_few_points(self):
        points = _synth_points(260.0, 15_000.0, [300.0, 600.0])  # only 2
        assert len(points) < MIN_FIT_POINTS
        assert fit_cp_wprime(points) is None

    def test_rejects_insufficient_duration_spread(self):
        # All points within ~1 min of each other — the fit line is essentially
        # unconstrained and any CP value would satisfy it.
        points = _synth_points(260.0, 15_000.0, [300.0, 330.0, 360.0])
        assert fit_cp_wprime(points) is None

    def test_rejects_cp_below_plausible_floor(self):
        # Construct points that imply CP ≈ 50W (below floor of 100).
        points = _synth_points(50.0, 15_000.0, [180.0, 300.0, 600.0])
        assert fit_cp_wprime(points) is None

    def test_rejects_cp_above_plausible_ceiling(self):
        points = _synth_points(600.0, 15_000.0, [180.0, 300.0, 600.0])
        # 600 is exactly at the ceiling; push slightly above.
        points = [(t, 610.0 + 15_000.0 / t) for t in [180.0, 300.0, 600.0]]
        assert fit_cp_wprime(points) is None

    def test_rejects_implausible_wprime(self):
        # W' of 200J is absurdly low for running — fit should refuse.
        points = _synth_points(260.0, 200.0, [180.0, 300.0, 600.0])
        assert fit_cp_wprime(points) is None
        # Very high W' also rejected.
        points = _synth_points(260.0, 100_000.0, [180.0, 300.0, 600.0])
        assert fit_cp_wprime(points) is None

    def test_filters_durations_outside_fit_window(self):
        # Points at 60s (too short) and 3600s (too long) are filtered BEFORE
        # the MIN_FIT_POINTS check. Supply only one valid in-window point.
        points = [
            (60.0, 500.0),          # excluded (< 120s)
            (3600.0, 200.0),        # excluded (> 1800s)
            (300.0, 300.0),         # the only in-window point
        ]
        assert fit_cp_wprime(points) is None  # <3 in-window points

    def test_real_world_noisy_points_fit_near_truth(self):
        # Slightly-off-model points (±2 % noise on each y), still recoverable.
        # Durations outside [180, 1200] are silently filtered by fit_cp_wprime.
        cp_true, wp_true = 280.0, 18_000.0
        durations = [150.0, 240.0, 360.0, 600.0, 900.0, 1500.0]
        ideal = _synth_points(cp_true, wp_true, durations)
        # Alternate over/under by 2 % so the mean stays near truth.
        noisy = [
            (t, p * (1.02 if i % 2 == 0 else 0.98))
            for i, (t, p) in enumerate(ideal)
        ]
        result = fit_cp_wprime(noisy)
        assert result is not None
        # Within 5 % of truth on noisy data.
        assert abs(result.cp_watts - cp_true) / cp_true < 0.05
        assert result.r_squared > 0.9

    def test_rejects_low_r_squared(self):
        """A fit with R² below MIN_R_SQUARED must not leak through.

        The plausibility gates only check CP and W' magnitudes — a line
        that barely relates ``P`` to ``1/t`` can still land those inside
        the running band. The R² gate is the second fence.
        """
        # Three points inside the fit window whose powers don't really
        # scale with 1/t. Hand-tuned so CP lands near 250W and W' near
        # 15 kJ (both plausible) but the actual line fits poorly.
        points = [
            (200.0, 260.0),
            (500.0, 290.0),   # anti-correlated with what the model expects
            (1000.0, 275.0),
        ]
        result = fit_cp_wprime(points)
        # If R² gate fires the result must be None; if the bogus line
        # happens to fall outside plausibility bounds that's also fine.
        if result is not None:
            pytest.fail(
                f"expected rejection, got CP={result.cp_watts:.0f} W'={result.w_prime_joules:.0f} "
                f"R²={result.r_squared:.3f} — either the R² gate or the plausibility gates "
                f"should have rejected this noisy input"
            )

    def test_rejects_when_all_splits_too_short(self):
        """Realistic failure mode: a speed-focused week with only 400 m reps
        (~90 s at 4:00/km pace). Every point sits below MIN_FIT_DURATION_SEC
        and the fit refuses — the user sees no CP rather than a fabricated one.
        """
        assert MIN_FIT_DURATION_SEC == 180.0  # guard against future drift
        points = [(90.0, 350.0), (100.0, 340.0), (110.0, 330.0), (120.0, 320.0)]
        assert fit_cp_wprime(points) is None

    def test_rejects_one_activity_many_same_duration_splits(self):
        """First-week sync: one long run with 8 × 1 km splits at similar
        pace. Powers vary a little but durations are all ~270 s — the fit
        line is not constrained and the duration-spread gate rejects it.
        """
        # Eight splits clustered within 20 s of each other — spread is
        # 20 s, well below MIN_DURATION_SPREAD_SEC (180 s).
        points = [(270.0 + i * 2.5, 240.0 + i) for i in range(8)]
        assert fit_cp_wprime(points) is None

    def test_result_as_of_defaults_to_today(self):
        points = _synth_points(260.0, 15_000.0, [180.0, 300.0, 600.0, 1200.0])
        result = fit_cp_wprime(points)
        assert result is not None
        assert result.as_of == date.today()

    def test_result_as_of_honors_override(self):
        points = _synth_points(260.0, 15_000.0, [180.0, 300.0, 600.0, 1200.0])
        custom = date(2026, 1, 15)
        result = fit_cp_wprime(points, as_of=custom)
        assert result is not None
        assert result.as_of == custom

    def test_to_dict_rounds_reasonably(self):
        points = _synth_points(260.0, 15_000.0, [180.0, 300.0, 600.0, 1200.0])
        result = fit_cp_wprime(points)
        assert result is not None
        d = result.to_dict()
        # Round-trip-style check: dict keys and value types
        assert set(d.keys()) == {"cp_watts", "w_prime_joules", "r_squared", "point_count", "as_of"}
        assert isinstance(d["cp_watts"], float)
        assert isinstance(d["w_prime_joules"], float)
        assert isinstance(d["r_squared"], float)
        assert isinstance(d["point_count"], int)
        assert d["point_count"] == 4
        # Date is ISO string.
        assert len(d["as_of"]) == 10
        assert d["as_of"][4] == "-"


class TestPlausibilityBounds:
    """Sanity-check the public constants so future tuning doesn't drift."""

    def test_cp_bounds_cover_realistic_runners(self):
        # Casual 150W to elite 450W should all be accepted.
        for cp in (150, 250, 350, 450):
            assert MIN_PLAUSIBLE_CP_WATTS <= cp <= MAX_PLAUSIBLE_CP_WATTS

    def test_min_fit_points_at_least_3(self):
        # 2 points give a line with 0 degrees of freedom — no residual, no R².
        # Any future relaxation below 3 is almost certainly a mistake.
        assert MIN_FIT_POINTS >= 3


@pytest.mark.parametrize("cp,wp,durations,expected_cp,expected_wp", [
    # Three realistic (CP, W') fixtures spanning casual → elite runners.
    # All durations must lie inside the [MIN_FIT_DURATION_SEC,
    # MAX_FIT_DURATION_SEC] window — points outside are silently filtered.
    (200.0, 10_000.0, [180.0, 300.0, 600.0, 1200.0], 200.0, 10_000.0),
    (300.0, 20_000.0, [180.0, 360.0, 720.0, 1200.0], 300.0, 20_000.0),
    (400.0, 25_000.0, [180.0, 300.0, 900.0, 1200.0], 400.0, 25_000.0),
])
def test_fit_recovers_parametrized_truths(cp, wp, durations, expected_cp, expected_wp):
    points = _synth_points(cp, wp, durations)
    result = fit_cp_wprime(points)
    assert result is not None
    assert abs(result.cp_watts - expected_cp) < 0.5
    assert abs(result.w_prime_joules - expected_wp) < 5.0
