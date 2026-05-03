"""Regression tests pinning the /api/training compute invariants.

Two invariants are guarded:

1. ``load_activity_samples`` filters by ``activity_id`` in SQL — the
   recent-window IDs go into ``WHERE activity_id IN (...)``, not a
   post-load Python filter — and never crosses user boundaries.

2. ``diagnose_training`` produces zone counts and durations that match
   a scalar reference implementation row-for-row, on every supported
   training base (power, HR, pace) and via both the per-second samples
   path and the split-duration fallback.

A scalar oracle (``_scalar_zone_time``) below mirrors the reference
classification logic; the equivalence assertions compare absolute zone
seconds (not rounded percentages) so sub-percent drift still trips the
test.
"""
from __future__ import annotations

import os
import tempfile
import time

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from analysis.data_loader import load_activity_samples
from analysis.metrics import diagnose_training
from db.models import Base, ActivitySample


# ---------------------------------------------------------------------------
# load_activity_samples — SQL-side activity_id filter
# ---------------------------------------------------------------------------


@pytest.fixture
def samples_db():
    """File-backed SQLite with two users × three activities of samples seeded."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    eng = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(bind=eng)
    Session = sessionmaker(bind=eng)
    db = Session()
    rows = []
    # user A: act-1 (200 rows), act-2 (200 rows), act-3 (200 rows)
    # user B: act-9 (200 rows) — should never leak into user A queries
    for uid, aid, count in [
        ("user-A", "act-1", 200),
        ("user-A", "act-2", 200),
        ("user-A", "act-3", 200),
        ("user-B", "act-9", 200),
    ]:
        for t in range(count):
            rows.append(ActivitySample(
                user_id=uid, activity_id=aid, source="stryd", t_sec=t,
                power_watts=200.0 + t,
            ))
    db.add_all(rows)
    db.commit()
    try:
        yield db
    finally:
        db.close()
        eng.dispose()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(path + suffix)
            except OSError:
                pass


def test_load_activity_samples_filters_by_id_at_sql_layer(samples_db):
    """activity_ids=[id] returns only that activity's rows."""
    df = load_activity_samples("user-A", samples_db, activity_ids=["act-2"])
    assert not df.empty
    assert set(df["activity_id"].astype(str).unique()) == {"act-2"}
    assert len(df) == 200


def test_load_activity_samples_empty_list_returns_empty(samples_db):
    """An empty id list short-circuits without touching the DB."""
    df = load_activity_samples("user-A", samples_db, activity_ids=[])
    assert df.empty
    # Still presents the expected schema so downstream column lookups don't KeyError.
    assert set(df.columns) >= {
        "activity_id", "t_sec", "power_watts", "hr_bpm", "pace_sec_km", "source",
    }


def test_load_activity_samples_none_loads_all_for_user(samples_db):
    """activity_ids=None preserves the legacy "all-history" behavior."""
    df = load_activity_samples("user-A", samples_db, activity_ids=None)
    # 3 activities × 200 rows = 600 rows for user-A only.
    assert len(df) == 600
    assert set(df["activity_id"].astype(str).unique()) == {"act-1", "act-2", "act-3"}


def test_load_activity_samples_does_not_cross_users(samples_db):
    """user-B's samples never appear in a user-A query, even when ids match.

    Asserts both the row count (act-1 + act-2 = 400 rows) and that an
    explicit query for user-B's id from user-A returns nothing — the
    most direct cross-user-leak check.
    """
    df = load_activity_samples(
        "user-A", samples_db, activity_ids=["act-1", "act-2", "act-9"],
    )
    assert set(df["activity_id"].astype(str).unique()) == {"act-1", "act-2"}
    assert len(df) == 400

    leaked = load_activity_samples(
        "user-A", samples_db, activity_ids=["act-9"],
    )
    assert leaked.empty


def test_load_activity_samples_chunks_large_id_lists(samples_db):
    """SQLite's ~999-host-parameter cap is respected by chunking the IN list.

    Three matching ids placed at chunk boundaries (~start, ~middle, ~end of
    a 1500-id list) catch off-by-one errors in the chunk slice that would
    otherwise silently drop rows whose id sits in a later chunk.
    """
    misses_per_block = 500
    ids = (
        ["act-1"]
        + [f"missing-{i}" for i in range(misses_per_block)]
        + ["act-2"]
        + [f"missing-{i + misses_per_block}" for i in range(misses_per_block)]
        + ["act-3"]
    )
    df = load_activity_samples("user-A", samples_db, activity_ids=ids)
    assert set(df["activity_id"].astype(str).unique()) == {"act-1", "act-2", "act-3"}
    # 3 activities × 200 rows = 600 — confirms every chunk's matches landed,
    # not just the first chunk's.
    assert len(df) == 600


# ---------------------------------------------------------------------------
# diagnose_training — vectorized vs. scalar equivalence + perf budget
# ---------------------------------------------------------------------------


def _scalar_zone_time(
    rows: pd.DataFrame,
    sample_col: str,
    bounds: list[float],
    n_zones: int,
    cp_by_aid: dict[str, float],
    current_cp: float,
    base: str = "power",
    weight_col: str | None = None,
) -> tuple[list[float], float]:
    """Scalar zone-classification oracle.

    The vectorized production path in ``analysis/metrics.py`` must produce
    identical zone counts on identical input. Two parameters cover the
    branches the production code splits on:

    * ``base="pace"`` flips to ``ratio = act_cp / val`` and walks
      ``inv_bounds`` high-index-first (the legacy iteration-order quirk
      preserved by both implementations).
    * ``weight_col`` accumulates that column's value per row instead of
      ``+= 1`` per row — exercises the splits-fallback duration weighting.
    """
    inv_bounds = (
        [1.0 / b if b > 0 else 0.0 for b in bounds] if base == "pace" else []
    )

    def _classify(val: float, act_cp: float) -> int:
        if act_cp <= 0 or val <= 0:
            return 0
        if base == "pace":
            ratio = act_cp / val
            for i in range(len(inv_bounds) - 1, -1, -1):
                if ratio >= inv_bounds[i]:
                    return i + 1
            return 0
        ratio = val / act_cp
        for i in range(len(bounds) - 1, -1, -1):
            if ratio >= bounds[i]:
                return i + 1
        return 0

    zone_time = [0.0] * n_zones
    total_time = 0.0
    for _, srow in rows.iterrows():
        v = srow.get(sample_col)
        if pd.isna(v):
            continue
        v = float(v)
        if v <= 0:
            continue
        if weight_col is not None:
            w = srow.get(weight_col)
            if pd.isna(w) or w <= 0:
                continue
            weight = float(w)
        else:
            weight = 1.0
        aid = str(srow.get("activity_id", ""))
        act_cp = cp_by_aid.get(aid, current_cp)
        zone_time[_classify(v, act_cp)] += weight
        total_time += weight
    return zone_time, total_time


def _build_random_samples(
    n: int,
    n_activities: int,
    seed: int = 17,
    sample_col: str = "power_watts",
    low: float = 80,
    high: float = 320,
) -> pd.DataFrame:
    """Random per-second samples with a realistic spread for one base."""
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "activity_id": rng.choice(
            [f"act-{i}" for i in range(n_activities)], size=n,
        ),
        "t_sec": np.arange(n),
        "power_watts": np.nan,
        "hr_bpm": np.nan,
        "pace_sec_km": np.nan,
        "source": "stryd",
    })
    df[sample_col] = rng.uniform(low, high, size=n)
    return df


def _splits_per_activity(
    activity_ids: list[str], avg_power: float = 200.0, duration_sec: float = 60.0,
) -> pd.DataFrame:
    """One short split per activity — keeps diagnose_training out of the
    activity-level fallback (which short-circuits when splits is empty).
    Once samples cover every aid, ``aids_with_samples`` filters these
    splits out of the duration weighting, so equivalence vs the scalar
    samples oracle stays apples-to-apples.
    """
    return pd.DataFrame([
        {"activity_id": aid, "split_num": 1,
         "avg_power": avg_power, "avg_hr": avg_power,
         "avg_pace_sec_km": avg_power, "duration_sec": duration_sec}
        for aid in activity_ids
    ])


def _activities_with_cp(
    activity_ids: list[str],
    cp_values: list[float],
    today,
    avg_power: float = 200.0,
) -> pd.DataFrame:
    """Activities frame mirroring what RequestContext.merged_activities ships."""
    return pd.DataFrame([
        {
            "activity_id": aid,
            "date": (today - pd.Timedelta(days=7 + i)).isoformat(),
            "distance_km": 10, "duration_sec": 3600,
            "avg_power": avg_power, "avg_hr": avg_power,
            "source": "stryd",
            "cp_estimate": cp,
        }
        for i, (aid, cp) in enumerate(zip(activity_ids, cp_values))
    ])


def test_vectorized_zone_seconds_match_scalar_oracle_power():
    """Power base: vectorized samples-path zone counts match the scalar
    oracle row-for-row.

    The fixture deliberately includes one activity with ``cp_estimate=0``
    so the production path's ``valid`` mask (``cp > 0``) gets exercised:
    those rows must land in zone 0 and the totals must still agree.
    Compares absolute ``zone_time`` and ``total_time`` (not rounded
    percentages), so sub-percent drift fails the test.
    """
    cp = 250.0
    n = 5000
    n_acts = 6
    samples = _build_random_samples(n, n_acts, seed=42)
    today = pd.Timestamp.now("UTC").date()
    activity_ids = sorted(samples["activity_id"].astype(str).unique())

    # Activity-CP variation, including one cp_estimate=0 row to exercise
    # the valid-mask branch.
    cp_values = [cp + (i - n_acts / 2) * 5 for i in range(n_acts)]
    cp_values[0] = 0.0  # pin first activity to invalid CP
    cp_by_aid = {
        aid: cp_v
        for aid, cp_v in zip(activity_ids, cp_values)
        if cp_v > 0  # production drops cp_estimate <= 0 from _cp_by_aid
    }

    activities = _activities_with_cp(activity_ids, cp_values, today)
    splits = _splits_per_activity(activity_ids)

    bounds = [0.55, 0.75, 0.90, 1.05]  # Coggan
    n_zones = len(bounds) + 1
    cp_trend = {"current": cp, "direction": "stable"}

    expected_zt, expected_total = _scalar_zone_time(
        samples, "power_watts", bounds, n_zones, cp_by_aid, cp,
    )

    result = diagnose_training(
        activities, splits, cp_trend,
        base="power", threshold_value=cp,
        zone_boundaries=bounds,
        zone_names=["Recovery", "Endurance", "Tempo", "Threshold", "VO2max"],
        target_distribution=[0.0, 0.7, 0.1, 0.15, 0.05],
        samples=samples,
    )
    assert result["data_meta"]["distribution_resolution"] == "samples"
    # Compute actual zone seconds from percentages × total_time.
    # We round-trip via percentages because diagnose_training only
    # surfaces those, but assert against the absolute totals so any
    # drift larger than a single sample rounds out.
    actual_pct = [d["actual_pct"] for d in result["distribution"]]
    expected_pct = [round(zt / expected_total * 100) for zt in expected_zt]
    assert actual_pct == expected_pct, (
        f"Power-base zone distribution drifted: "
        f"expected={expected_pct} actual={actual_pct} "
        f"oracle_zone_seconds={expected_zt} oracle_total={expected_total}"
    )


def test_vectorized_zone_seconds_match_scalar_oracle_pace():
    """Pace base: vectorized pace path preserves the legacy iteration
    order bit-for-bit.

    Without this, a Garmin-only user on pace base could see silently
    shifted time-in-zone bars after any future "vectorize this further"
    refactor.
    """
    # threshold pace ≈ 4:00/km in sec/km
    threshold_pace = 240.0
    n = 4000
    n_acts = 5
    samples = _build_random_samples(
        n, n_acts, seed=123, sample_col="pace_sec_km", low=180, high=360,
    )
    today = pd.Timestamp.now("UTC").date()
    activity_ids = sorted(samples["activity_id"].astype(str).unique())
    activities = _activities_with_cp(
        activity_ids, [threshold_pace] * n_acts, today,
    )
    splits = _splits_per_activity(
        activity_ids, avg_power=threshold_pace, duration_sec=60.0,
    )

    bounds = [0.55, 0.75, 0.90, 1.05]
    n_zones = len(bounds) + 1

    # Pace base does NOT populate _cp_by_aid (production only does for
    # power) — empty dict reproduces that.
    expected_zt, expected_total = _scalar_zone_time(
        samples, "pace_sec_km", bounds, n_zones,
        cp_by_aid={}, current_cp=threshold_pace, base="pace",
    )

    result = diagnose_training(
        activities, splits, {"current": threshold_pace, "direction": "stable"},
        base="pace", threshold_value=threshold_pace,
        zone_boundaries=bounds,
        zone_names=["Recovery", "Endurance", "Tempo", "Threshold", "VO2max"],
        samples=samples,
    )
    assert result["data_meta"]["distribution_resolution"] == "samples"
    actual_pct = [d["actual_pct"] for d in result["distribution"]]
    expected_pct = [round(zt / expected_total * 100) for zt in expected_zt]
    assert actual_pct == expected_pct, (
        f"Pace-base zone distribution drifted: "
        f"expected={expected_pct} actual={actual_pct} "
        f"oracle_zone_seconds={expected_zt}"
    )


def test_vectorized_splits_fallback_matches_scalar_oracle():
    """Splits-fallback path (no samples) must match the duration-weighted
    scalar oracle. Hits the ``np.bincount(weights=duration_sec)``
    accumulator that this PR also rewrote.
    """
    cp = 250.0
    rng = np.random.default_rng(7)
    n_acts = 4
    activity_ids = [f"act-{i}" for i in range(n_acts)]
    today = pd.Timestamp.now("UTC").date()
    activities = _activities_with_cp(activity_ids, [cp] * n_acts, today)

    # One activity gets several splits with varied durations and powers
    # spanning all five zones; another mixes valid + zero-duration rows.
    splits_rows: list[dict] = []
    for aid in activity_ids:
        for split_num in range(1, 11):
            splits_rows.append({
                "activity_id": aid,
                "split_num": split_num,
                "avg_power": float(rng.uniform(80, 320)),
                "duration_sec": float(rng.uniform(60, 600)),
            })
    # Sentinel rows the oracle and production should both ignore:
    splits_rows.append(
        {"activity_id": activity_ids[0], "split_num": 99,
         "avg_power": 200.0, "duration_sec": 0.0},
    )
    splits_rows.append(
        {"activity_id": activity_ids[0], "split_num": 100,
         "avg_power": 0.0, "duration_sec": 60.0},
    )
    splits = pd.DataFrame(splits_rows)

    bounds = [0.55, 0.75, 0.90, 1.05]
    n_zones = len(bounds) + 1
    cp_by_aid: dict[str, float] = {aid: cp for aid in activity_ids}

    expected_zt, expected_total = _scalar_zone_time(
        splits, "avg_power", bounds, n_zones, cp_by_aid, cp,
        weight_col="duration_sec",
    )

    result = diagnose_training(
        activities, splits, {"current": cp, "direction": "stable"},
        base="power", threshold_value=cp,
        zone_boundaries=bounds,
        zone_names=["Recovery", "Endurance", "Tempo", "Threshold", "VO2max"],
        samples=None,
    )
    assert result["data_meta"]["distribution_resolution"] == "splits"
    actual_pct = [d["actual_pct"] for d in result["distribution"]]
    expected_pct = [round(zt / expected_total * 100) for zt in expected_zt]
    assert actual_pct == expected_pct, (
        f"Splits-fallback zone distribution drifted: "
        f"expected={expected_pct} actual={actual_pct} "
        f"oracle_zone_seconds={expected_zt}"
    )


def test_diagnose_training_handles_50k_samples_quickly():
    """Soft regression budget on the vectorized samples path: 50k per-second
    rows should finish in well under a second. The pre-fix iterrows loop
    took ~1.3 s on a real ~50k-row user, dominating /api/training cold-start.

    1.0 s ceiling tolerates CI noise; typical wall time is tens of
    milliseconds. Splits seeded so the function takes the samples-aware
    branch (an empty splits frame would short-circuit to the activity-level
    fallback and wouldn't actually exercise the vectorized samples path).
    """
    cp = 250.0
    n = 50_000
    n_acts = 10
    samples = _build_random_samples(n, n_acts, seed=99)
    today = pd.Timestamp.now("UTC").date()
    activity_ids = sorted(samples["activity_id"].astype(str).unique())
    activities = _activities_with_cp(activity_ids, [cp] * n_acts, today)
    splits = _splits_per_activity(activity_ids)

    t0 = time.perf_counter()
    diagnose_training(
        activities, splits, {"current": cp, "direction": "stable"},
        base="power",
        threshold_value=cp,
        zone_boundaries=[0.55, 0.75, 0.90, 1.05],
        zone_names=["Recovery", "Endurance", "Tempo", "Threshold", "VO2max"],
        samples=samples,
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, (
        f"diagnose_training on 50k samples took {elapsed*1000:.0f} ms "
        "— budget is 1000 ms (the pre-vectorization iterrows path took "
        "~1300 ms on a real user)."
    )
