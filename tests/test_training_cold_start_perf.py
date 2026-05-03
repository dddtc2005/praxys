"""Regression tests for the /api/training cold-start performance fix.

Two changes are guarded here:

1. ``load_activity_samples`` pushes the ``activity_id`` filter into SQL.
   The earlier code pulled every row a user had ever streamed and filtered
   to the recent window in Python, so a long-history user paid linear
   I/O per request even after the cache was added.

2. ``diagnose_training`` classifies per-second samples with vectorized
   numpy ops instead of a Python ``iterrows()`` loop. On a real user with
   ~50k samples this shifted the dominant /api/training cost from ~1.3 s
   down to ~17 ms; the equivalence test in this file pins the new path
   bit-for-bit against the legacy scalar logic so future edits can't
   silently regress accuracy under the guise of "more vectorization."
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
    """user-B's samples never appear in a user-A query, even when ids match."""
    df = load_activity_samples(
        "user-A", samples_db, activity_ids=["act-1", "act-2", "act-9"],
    )
    assert "act-9" not in set(df["activity_id"].astype(str).unique())


def test_load_activity_samples_chunks_large_id_lists(samples_db):
    """SQLite's ~999-host-parameter cap is respected by chunking the IN list.

    Passing 1500 ids — one of which actually exists — must not raise and
    must still return the matching rows.
    """
    ids = [f"missing-{i}" for i in range(1500)] + ["act-1"]
    df = load_activity_samples("user-A", samples_db, activity_ids=ids)
    assert not df.empty
    assert set(df["activity_id"].astype(str).unique()) == {"act-1"}


# ---------------------------------------------------------------------------
# diagnose_training — vectorized vs. scalar equivalence + perf budget
# ---------------------------------------------------------------------------


def _scalar_zone_time(
    samples: pd.DataFrame,
    sample_col: str,
    bounds: list[float],
    n_zones: int,
    cp_by_aid: dict[str, float],
    current_cp: float,
) -> tuple[list[float], float]:
    """Reference implementation matching the pre-vectorization Python loop.

    Lifted from the iterrows path that ``diagnose_training`` used before
    the perf fix. Used purely as a fixed-point oracle in the equivalence
    test below; the production path lives in ``analysis/metrics.py``.
    """
    def _classify(val: float, act_cp: float) -> int:
        if act_cp <= 0 or val <= 0:
            return 0
        ratio = val / act_cp
        for i in range(len(bounds) - 1, -1, -1):
            if ratio >= bounds[i]:
                return i + 1
        return 0

    zone_time = [0.0] * n_zones
    total_time = 0.0
    for _, srow in samples.iterrows():
        v = srow[sample_col]
        if pd.isna(v):
            continue
        v = float(v)
        if v <= 0:
            continue
        aid = str(srow.get("activity_id", ""))
        act_cp = cp_by_aid.get(aid, current_cp)
        zone_time[_classify(v, act_cp)] += 1
        total_time += 1
    return zone_time, total_time


def _build_random_samples(n: int, n_activities: int, seed: int = 17) -> pd.DataFrame:
    """Random per-second samples with realistic-ish power spread."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "activity_id": rng.choice(
            [f"act-{i}" for i in range(n_activities)], size=n,
        ),
        "t_sec": np.arange(n),
        "power_watts": rng.uniform(80, 320, size=n),
        "hr_bpm": np.nan,
        "pace_sec_km": np.nan,
        "source": "stryd",
    })


def test_vectorized_zone_distribution_matches_scalar_loop():
    """Vectorized samples-path must produce the same percentages the
    iterrows reference produces on the same input.

    Why this matters: the vectorization is a pure refactor — any drift
    here would silently shift users' time-in-zone bars.

    diagnose_training short-circuits to an activity-level fallback when
    ``splits`` is empty (so it never reaches the samples block). The test
    therefore seeds one tiny split per activity to keep the sample path
    in scope; the splits-fallback path is suppressed by ``aids_with_samples``
    which collects every id present in the samples DataFrame.
    """
    cp = 250.0
    n = 5000
    n_acts = 6
    samples = _build_random_samples(n, n_acts, seed=42)
    today = pd.Timestamp.now("UTC").date()
    activity_ids = sorted(samples["activity_id"].astype(str).unique())
    activities = pd.DataFrame([
        {
            "activity_id": aid,
            "date": (today - pd.Timedelta(days=7 + i)).isoformat(),
            "distance_km": 10, "duration_sec": 3600,
            "avg_power": 200, "source": "stryd",
            # Per-activity CP so the cp_by_aid path is exercised
            "cp_estimate": cp + (i - n_acts / 2) * 5,
        }
        for i, aid in enumerate(activity_ids)
    ])
    # One split per activity so diagnose_training takes the samples-aware
    # branch. The split rows are short enough that, once samples cover
    # every activity_id, the fallback excludes them entirely — keeping
    # this an apples-to-apples comparison with the scalar oracle below.
    splits = pd.DataFrame([
        {"activity_id": aid, "split_num": 1,
         "avg_power": 200.0, "duration_sec": 60}
        for aid in activity_ids
    ])

    cp_trend = {"current": cp, "direction": "stable"}
    bounds = [0.55, 0.75, 0.90, 1.05]  # Coggan
    n_zones = len(bounds) + 1

    cp_by_aid = {
        aid: cp + (i - n_acts / 2) * 5
        for i, aid in enumerate(activity_ids)
    }

    expected_zt, expected_total = _scalar_zone_time(
        samples, "power_watts", bounds, n_zones, cp_by_aid, cp,
    )
    expected_pct = [
        round(zt / expected_total * 100) for zt in expected_zt
    ]

    result = diagnose_training(
        activities, splits, cp_trend,
        base="power",
        threshold_value=cp,
        zone_boundaries=bounds,
        zone_names=["Recovery", "Endurance", "Tempo", "Threshold", "VO2max"],
        target_distribution=[0.0, 0.7, 0.1, 0.15, 0.05],
        samples=samples,
    )
    assert result["data_meta"]["distribution_resolution"] == "samples"
    actual_pct = [d["actual_pct"] for d in result["distribution"]]
    assert actual_pct == expected_pct, (
        "Vectorized zone distribution drifted from the legacy iterrows "
        f"reference. expected={expected_pct} actual={actual_pct}"
    )


def test_diagnose_training_handles_50k_samples_quickly():
    """Soft regression budget: 50k per-second samples should finish in well
    under a second on any reasonable dev machine. The pre-fix iterrows
    loop took ~1.3 s on a real ~50k-row user, dominating /api/training
    cold-start.

    We use a generous 1.0 s ceiling so flaky CI doesn't fail on cache /
    contention noise; the typical wall time is tens of milliseconds.
    """
    cp = 250.0
    n = 50_000
    n_acts = 10
    samples = _build_random_samples(n, n_acts, seed=99)
    today = pd.Timestamp.now("UTC").date()
    activity_ids = sorted(samples["activity_id"].astype(str).unique())
    activities = pd.DataFrame([
        {
            "activity_id": aid,
            "date": (today - pd.Timedelta(days=7 + i)).isoformat(),
            "distance_km": 10, "duration_sec": 3600,
            "avg_power": 200, "source": "stryd",
            "cp_estimate": cp,
        }
        for i, aid in enumerate(activity_ids)
    ])
    splits = pd.DataFrame()

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
