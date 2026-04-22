"""Derive Critical Power from activity power observations.

Fits the canonical 2-parameter hyperbolic CP model (Monod & Scherrer 1965,
Jones et al. 2010) to the user's own best-effort power-vs-duration points:

    P(t) = CP + W' / t

where ``CP`` (watts) is the asymptote — the highest power sustainable for
theoretically indefinite duration — and ``W'`` (joules) is the finite work
capacity above CP. The fit is a linear regression after reparametrising
``P`` against ``1/t``: slope = W', intercept = CP.

**Why this exists.** The app already accepts CP values written by each
connected source (Stryd's Power Center, Garmin's ``functionalThresholdPower``
endpoint). For a user running Stryd via Connect-IQ on Garmin but without a
direct Stryd account, the activity-level power field carries Stryd power
while the only CP source available is Garmin's native FTP estimate — a
number derived from a *different* power pipeline and typically ~30 % higher
than Stryd (see ``docs/dev/gotchas.md``). That mismatch produces wrong
load, wrong race predictions, and wrong training targets.

Activity-derived CP always matches the power source the activities
actually carry, because it IS that source.

**Data constraints.** We only have activity-level and per-split (lap)
averages — no per-second power streams. The finest resolution for
"best power over N seconds" is therefore the shortest lap the user recorded.
Typical lap durations fall between ~90 s (400 m repeats) and ~300 s (1 km
splits). We bin candidate points by duration and keep the peak power per
bin to approximate the mean-maximal power curve.

Sources:
    - Monod H, Scherrer J. (1965) The work capacity of a synergic
      muscular group. *Ergonomics* 8(3):329-338.
    - Jones AM, Vanhatalo A, Burnley M et al. (2010) Critical power:
      implications for determination of VO2max and exercise tolerance.
      *Med Sci Sports Exerc* 42(10):1876-1890.
      https://doi.org/10.1249/MSS.0b013e3181d9cf7f
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# --- Fit acceptance thresholds -----------------------------------------------

# Durations outside this band are excluded from the fit. Below 120 s the
# hyperbolic model is dominated by anaerobic capacity (W') and asymptotes
# poorly; above 1800 s (30 min) efforts approach CP and add little leverage
# while being noisier in practice. Jones et al. 2010 recommend 2–15 min for
# lab testing; we widen slightly to accommodate long-split field data.
MIN_FIT_DURATION_SEC = 120.0
MAX_FIT_DURATION_SEC = 1800.0

# Physiologically-plausible running CP window. Outside this, the fit is
# almost certainly an artefact of noisy splits (warmup spike, GPS error,
# pauses). Casual runners land ~150–250 W; trained ~260–360 W; elites ~380+.
MIN_PLAUSIBLE_CP_WATTS = 100.0
MAX_PLAUSIBLE_CP_WATTS = 500.0

# W' (anaerobic work capacity) in joules. Typical 8–25 kJ for runners.
# Below 2 kJ the model reduces to a flat line (CP only); above 60 kJ the
# fit is picking up a short-effort outlier rather than a real W'.
MIN_PLAUSIBLE_WPRIME_J = 2_000.0
MAX_PLAUSIBLE_WPRIME_J = 60_000.0

# Minimum points required to trust the fit. 2 gives a line; 3+ gives
# something resembling confidence. We also require spread across the
# duration range.
MIN_FIT_POINTS = 3
MIN_DURATION_SPREAD_SEC = 180.0  # shortest and longest must differ by ≥3 min

# Duration bins for peak-power collection. Each (min, max) is inclusive of
# min, exclusive of max; we keep the single highest-power point per bin.
_DURATION_BINS_SEC: tuple[tuple[float, float], ...] = (
    (60.0, 180.0),     # ~1–3 min
    (180.0, 360.0),    # 3–6 min
    (360.0, 720.0),    # 6–12 min
    (720.0, 1200.0),   # 12–20 min
    (1200.0, 1800.0),  # 20–30 min
    (1800.0, 3600.0),  # 30–60 min
)


@dataclass(frozen=True)
class CpFitResult:
    """A CP fit with its diagnostic data.

    ``r_squared`` is the coefficient of determination of the linear fit in
    ``P`` vs ``1/t``. The ``points`` list is what actually went into the
    fit — exposed for debugging and UI tooltips.
    """

    cp_watts: float
    w_prime_joules: float
    r_squared: float
    points: list[tuple[float, float]]  # (duration_sec, power_watts)
    as_of: date

    def to_dict(self) -> dict:
        return {
            "cp_watts": round(self.cp_watts, 1),
            "w_prime_joules": round(self.w_prime_joules, 0),
            "r_squared": round(self.r_squared, 3),
            "point_count": len(self.points),
            "as_of": self.as_of.isoformat(),
        }


def collect_mean_max_points(
    observations: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Reduce raw (duration, power) observations to best-power-per-duration-bin.

    ``observations`` is a flat list of per-split and per-activity
    (duration_sec, avg_power_watts) tuples collected across the fit window.
    We bin by duration and keep the highest-power entry from each bin — an
    approximation of the mean-maximal power curve given that our data is
    lap-level rather than per-second.

    Returns the bin representatives sorted by duration ascending. Bins with
    no data are simply omitted.
    """
    best_by_bin: dict[tuple[float, float], tuple[float, float]] = {}
    for duration, power in observations:
        if duration is None or power is None:
            continue
        if duration <= 0 or power <= 0:
            continue
        for lo, hi in _DURATION_BINS_SEC:
            if lo <= duration < hi:
                current = best_by_bin.get((lo, hi))
                if current is None or power > current[1]:
                    best_by_bin[(lo, hi)] = (duration, power)
                break
    return sorted(best_by_bin.values(), key=lambda p: p[0])


def fit_cp_wprime(
    points: list[tuple[float, float]],
    as_of: date | None = None,
) -> CpFitResult | None:
    """Least-squares fit of ``P = CP + W'/t`` to ``points``.

    ``points`` is a list of ``(duration_sec, power_watts)`` tuples. Only
    points inside ``[MIN_FIT_DURATION_SEC, MAX_FIT_DURATION_SEC]`` are
    used — shorter efforts bias toward W' and longer efforts flatten
    toward CP.

    Returns ``None`` (not a partial result) when the fit is untrustworthy:

    - fewer than ``MIN_FIT_POINTS`` usable points
    - duration spread below ``MIN_DURATION_SPREAD_SEC`` (the fit line is
      not meaningfully constrained by a single-duration cluster)
    - coefficients fall outside the plausible CP / W' windows (likely a
      noisy split, not a real threshold)

    Refusing to return a number is intentional: a bad CP silently written
    into the database would mislead every downstream load / prediction
    calculation. Data sufficiency gates belong at the source, not downstream.
    """
    valid = [
        (d, p)
        for d, p in points
        if MIN_FIT_DURATION_SEC <= d <= MAX_FIT_DURATION_SEC
    ]
    if len(valid) < MIN_FIT_POINTS:
        return None
    durations = [d for d, _ in valid]
    if max(durations) - min(durations) < MIN_DURATION_SPREAD_SEC:
        return None

    xs = [1.0 / d for d, _ in valid]  # 1/t
    ys = [p for _, p in valid]        # P
    n = len(valid)
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n

    # slope (W') and intercept (CP) via ordinary least squares
    cov = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    var_x = sum((x - x_mean) ** 2 for x in xs)
    if var_x == 0:
        return None
    w_prime = cov / var_x
    cp = y_mean - w_prime * x_mean

    # R²
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    if ss_tot == 0:
        return None
    ss_res = sum((y - (cp + w_prime * x)) ** 2 for x, y in zip(xs, ys))
    r_squared = 1.0 - (ss_res / ss_tot)

    if not (MIN_PLAUSIBLE_CP_WATTS <= cp <= MAX_PLAUSIBLE_CP_WATTS):
        return None
    if not (MIN_PLAUSIBLE_WPRIME_J <= w_prime <= MAX_PLAUSIBLE_WPRIME_J):
        return None

    return CpFitResult(
        cp_watts=cp,
        w_prime_joules=w_prime,
        r_squared=r_squared,
        points=valid,
        as_of=as_of or date.today(),
    )


def estimate_cp_from_activities(
    user_id: str,
    db: Session,
    *,
    lookback_days: int = 90,
    today: date | None = None,
) -> CpFitResult | None:
    """Derive a CP estimate from the user's own splits + activities.

    Reads from ``activity_splits`` (primary source — lap-level granularity)
    and ``activities`` (fallback — full-activity averages) over the last
    ``lookback_days`` days. Returns ``None`` when there isn't enough data
    for a trustworthy fit, in which case the caller should NOT write a row:
    a missing CP beats a wrong CP.
    """
    from db.models import Activity, ActivitySplit

    as_of = today or date.today()
    since = as_of - timedelta(days=lookback_days)

    splits = (
        db.query(ActivitySplit.duration_sec, ActivitySplit.avg_power, Activity.date)
        .join(
            Activity,
            (Activity.activity_id == ActivitySplit.activity_id)
            & (Activity.user_id == ActivitySplit.user_id),
        )
        .filter(
            ActivitySplit.user_id == user_id,
            Activity.date >= since,
            ActivitySplit.duration_sec.isnot(None),
            ActivitySplit.avg_power.isnot(None),
        )
        .all()
    )
    activity_level = (
        db.query(Activity.duration_sec, Activity.avg_power)
        .filter(
            Activity.user_id == user_id,
            Activity.date >= since,
            Activity.duration_sec.isnot(None),
            Activity.avg_power.isnot(None),
        )
        .all()
    )

    observations: list[tuple[float, float]] = []
    for row in splits:
        observations.append((float(row.duration_sec), float(row.avg_power)))
    for row in activity_level:
        observations.append((float(row.duration_sec), float(row.avg_power)))

    points = collect_mean_max_points(observations)
    return fit_cp_wprime(points, as_of=as_of)
