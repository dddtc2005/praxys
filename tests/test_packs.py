"""Unit tests for the per-endpoint dashboard packs (issue #146).

Each pack is verified end-to-end against a small SQLite DB so the test
exercises the same code path the real /api/* routes do (loader → dedup →
EWMA → metrics) without going through FastAPI.

The shape contracts here are the source of truth that the route wiring
upstream depends on — if a pack drops a key the route was forwarding,
TypeScript on the frontend would receive `undefined` for that field.
"""
from __future__ import annotations

import tempfile
from datetime import date, timedelta

import pytest


@pytest.fixture
def db_with_seeded_user(monkeypatch):
    """Yield (db, user_id) for a SQLite DB pre-seeded with realistic data.

    The seed gives each pack enough to compute non-empty results:
    activities (with cp_estimate + power), splits, recovery rows, a plan,
    and a profile threshold. ``RequestContext`` reads from this DB.
    """
    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    monkeypatch.setenv("DATA_DIR", tmpdir.name)
    monkeypatch.setenv(
        "PRAXYS_LOCAL_ENCRYPTION_KEY",
        "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=",
    )
    from db import session as db_session
    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    from db.models import (
        Activity,
        ActivitySplit,
        FitnessData,
        RecoveryData,
        TrainingPlan,
        User,
    )

    user_id = "test-user-packs"
    db = db_session.SessionLocal()
    db.add(User(id=user_id, email="packs@example.com", hashed_password="x"))

    today = date.today()
    # Two weeks of activities — enough to produce CTL/ATL movement and a
    # CP-trend chart with ≥3 points.
    for i in range(14):
        d = today - timedelta(days=14 - i)
        db.add(Activity(
            user_id=user_id,
            activity_id=f"act-{i}",
            date=d,
            activity_type="running",
            distance_km=8.0 + (i % 3),
            duration_sec=2400.0 + i * 60,
            avg_power=240.0 + i,
            max_power=300.0 + i,
            avg_hr=150.0 + (i % 5),
            max_hr=170.0,
            cp_estimate=265.0 + i * 0.5,
            rss=70.0 + i * 2,
            source="stryd",
        ))
        db.add(ActivitySplit(
            user_id=user_id,
            activity_id=f"act-{i}",
            split_num=1,
            distance_km=4.0,
            duration_sec=1200.0,
            avg_power=245.0,
            avg_hr=152.0,
            avg_pace_min_km="5:00",
        ))
        db.add(RecoveryData(
            user_id=user_id, date=d,
            sleep_score=80.0 + (i % 10),
            hrv_avg=50.0 + (i % 8),
            resting_hr=50.0,
            readiness_score=75.0 + (i % 15),
            source="oura",
        ))

    db.add(FitnessData(
        user_id=user_id, date=today, metric_type="cp_estimate",
        value=270.0, source="stryd",
    ))

    # A planned workout for today + tomorrow so signal / week_load /
    # upcoming all have something to render.
    db.add(TrainingPlan(
        user_id=user_id, date=today,
        workout_type="tempo", planned_duration_min=45,
        target_power_min=240, target_power_max=260,
        source="stryd",
    ))
    db.add(TrainingPlan(
        user_id=user_id, date=today + timedelta(days=1),
        workout_type="long", planned_duration_min=90,
        target_power_min=220, target_power_max=240,
        source="stryd",
    ))
    db.commit()

    try:
        yield db, user_id
    finally:
        db.close()
        if db_session.engine is not None:
            db_session.engine.dispose()
        db_session.engine = None
        db_session.SessionLocal = None
        db_session.async_engine = None
        db_session.AsyncSessionLocal = None
        tmpdir.cleanup()


def _ctx(db_with_seeded_user):
    from api.packs import RequestContext
    db, user_id = db_with_seeded_user
    return RequestContext(user_id=user_id, db=db)


def test_request_context_caches_shared_inputs(db_with_seeded_user):
    """cached_property must hand back the same object on second access.

    A fresh deduplication or threshold resolution per pack would defeat
    the whole point of the request-scoped cache.
    """
    ctx = _ctx(db_with_seeded_user)
    assert ctx.merged_activities is ctx.merged_activities
    assert ctx.thresholds is ctx.thresholds
    assert ctx.science is ctx.science
    assert ctx.fitness_series is ctx.fitness_series


def test_signal_pack_returns_required_keys(db_with_seeded_user):
    from api.packs import get_signal_pack
    ctx = _ctx(db_with_seeded_user)
    out = get_signal_pack(ctx)
    assert set(out.keys()) == {
        "signal", "tsb_sparkline", "recovery_analysis", "warnings",
    }
    assert "dates" in out["tsb_sparkline"]
    assert "values" in out["tsb_sparkline"]
    assert isinstance(out["warnings"], list)


def test_today_widgets_pack_returns_required_keys(db_with_seeded_user):
    from api.packs import get_today_widgets
    ctx = _ctx(db_with_seeded_user)
    out = get_today_widgets(ctx)
    assert set(out.keys()) == {"last_activity", "week_load", "upcoming"}
    # Last activity is the most recent of the seeded 14 — must round-trip.
    assert out["last_activity"] is not None
    assert out["last_activity"]["date"]
    # Upcoming should include tomorrow's planned long run.
    assert any(w.get("workout_type") == "long" for w in out["upcoming"])


def test_diagnosis_pack_returns_required_keys(db_with_seeded_user):
    from api.packs import get_diagnosis_pack
    ctx = _ctx(db_with_seeded_user)
    out = get_diagnosis_pack(ctx)
    assert set(out.keys()) == {"diagnosis", "workout_flags", "sleep_perf"}
    assert isinstance(out["workout_flags"], list)
    # sleep_perf carries metric metadata even when pairs are empty.
    assert "metric_label" in out["sleep_perf"]
    assert "metric_unit" in out["sleep_perf"]


def test_fitness_pack_returns_required_keys(db_with_seeded_user):
    from api.packs import get_fitness_pack
    ctx = _ctx(db_with_seeded_user)
    out = get_fitness_pack(ctx)
    assert set(out.keys()) == {"fitness_fatigue", "cp_trend", "weekly_review"}
    ff = out["fitness_fatigue"]
    assert {"dates", "ctl", "atl", "tsb"}.issubset(ff.keys())
    assert {
        "projected_dates", "projected_ctl", "projected_atl", "projected_tsb",
    }.issubset(ff.keys())
    # ctl/atl/tsb track each other; dates spans the full display window even
    # when the EWMA series is shorter (legacy `get_dashboard_data` behavior).
    assert len(ff["ctl"]) == len(ff["atl"]) == len(ff["tsb"])
    assert len(ff["dates"]) >= len(ff["ctl"])
    assert len(ff["projected_dates"]) == len(ff["projected_tsb"]) == 14


def test_race_pack_returns_required_keys(db_with_seeded_user):
    from api.packs import get_race_pack
    ctx = _ctx(db_with_seeded_user)
    out = get_race_pack(ctx)
    assert set(out.keys()) == {
        "race_countdown", "cp_trend", "cp_trend_data", "latest_cp",
    }
    # Continuous improvement (no race_date in default config) → mode set.
    assert out["race_countdown"]["mode"] in {
        "continuous", "cp_milestone", "race_date",
    }


def test_history_pack_returns_full_activity_list(db_with_seeded_user):
    from api.packs import get_history_pack
    ctx = _ctx(db_with_seeded_user)
    out = get_history_pack(ctx)
    assert set(out.keys()) == {"activities"}
    assert len(out["activities"]) == 14, "all seeded activities should appear"
    # Each activity carries its splits.
    assert all("splits" in a for a in out["activities"])


def test_science_pack_returns_required_keys(db_with_seeded_user):
    from api.packs import get_science_pack
    ctx = _ctx(db_with_seeded_user)
    out = get_science_pack(ctx)
    assert set(out.keys()) == {"science", "science_notes", "tsb_zones"}
    assert isinstance(out["science_notes"], dict)
    # Every pillar with a theory must contribute a note.
    for pillar, note in out["science_notes"].items():
        assert {"name", "description", "citations"} <= set(note.keys())


def test_packs_share_cache_across_calls(db_with_seeded_user, monkeypatch):
    """A route calling multiple packs must dedup the underlying loads.

    We patch ``load_data_from_db`` to count invocations: even after
    invoking three packs that all read activities/recovery/plan, the
    loader must run exactly once.
    """
    from api import packs as packs_mod
    real_loader = packs_mod.load_data_from_db
    calls = {"n": 0}

    def counting_loader(user_id, db):
        calls["n"] += 1
        return real_loader(user_id, db)

    monkeypatch.setattr(packs_mod, "load_data_from_db", counting_loader)

    db, user_id = db_with_seeded_user
    ctx = packs_mod.RequestContext(user_id=user_id, db=db)
    packs_mod.get_signal_pack(ctx)
    packs_mod.get_today_widgets(ctx)
    packs_mod.get_diagnosis_pack(ctx)

    assert calls["n"] == 1, (
        f"expected loader to run exactly once per request, got {calls['n']}"
    )


def test_dashboard_data_and_packs_agree_on_signal(db_with_seeded_user):
    """Behavioral equivalence: signal_pack output equals dashboard_data['signal'].

    Backstop against drift while ``get_dashboard_data`` is still in use by
    legacy callers (api/ai.py, api/routes/plan.py, MCP server).
    """
    from api.deps import get_dashboard_data
    from api.packs import RequestContext, get_signal_pack

    db, user_id = db_with_seeded_user
    full = get_dashboard_data(user_id=user_id, db=db)
    pack = get_signal_pack(RequestContext(user_id=user_id, db=db))

    assert pack["signal"] == full["signal"]
    assert pack["tsb_sparkline"] == full["tsb_sparkline"]
    assert pack["warnings"] == full["warnings"]
