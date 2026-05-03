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
    """Default call (no limit) returns every activity, with splits, plus
    the pagination/source-filter metadata the route forwards.
    """
    from api.packs import get_history_pack
    ctx = _ctx(db_with_seeded_user)
    out = get_history_pack(ctx)
    assert set(out.keys()) == {"activities", "total", "source_filter"}
    assert len(out["activities"]) == 14, "all seeded activities should appear"
    assert out["total"] == 14
    # Each activity carries its splits.
    assert all("splits" in a for a in out["activities"])


def test_history_pack_paginates_without_building_dropped_activities(
    db_with_seeded_user, monkeypatch,
):
    """``limit`` and ``offset`` slice activities BEFORE
    ``_build_activities_list`` runs, so the formatter only ever sees the
    requested page. The previous shape built every activity (with its
    splits) and let the route discard the surplus — wasted work that
    grew linearly with history size.
    """
    from api import packs as packs_mod

    builder_call_sizes: list[int] = []
    real_builder = packs_mod._build_activities_list

    def counting_builder(merged, splits):
        builder_call_sizes.append(len(merged))
        return real_builder(merged, splits)

    monkeypatch.setattr(packs_mod, "_build_activities_list", counting_builder)

    ctx = _ctx(db_with_seeded_user)
    out = packs_mod.get_history_pack(ctx, limit=5, offset=0)

    assert len(out["activities"]) == 5
    assert out["total"] == 14
    assert builder_call_sizes == [5], (
        "builder should receive only the page slice, not the full list "
        f"(saw call sizes {builder_call_sizes})"
    )


def test_history_pack_offset_returns_correct_slice(db_with_seeded_user):
    """``offset`` skips from the start of the date-descending list, so
    page-2 of size-5 returns activities 6-10 of 14.
    """
    from api.packs import get_history_pack

    ctx = _ctx(db_with_seeded_user)
    page1 = get_history_pack(ctx, limit=5, offset=0)
    page2 = get_history_pack(ctx, limit=5, offset=5)

    assert page1["total"] == page2["total"] == 14
    assert len(page1["activities"]) == 5
    assert len(page2["activities"]) == 5
    page1_ids = {a["activity_id"] for a in page1["activities"]}
    page2_ids = {a["activity_id"] for a in page2["activities"]}
    assert page1_ids.isdisjoint(page2_ids), (
        "page 1 and page 2 must not overlap"
    )
    # Date order: page-1 dates strictly newer than (or equal at boundary)
    # page-2 dates.
    assert max(a["date"] for a in page2["activities"]) <= min(
        a["date"] for a in page1["activities"]
    )


def test_history_pack_sliced_splits_match_full_build(db_with_seeded_user):
    """Slicing splits to the page's activity_ids must produce the same
    per-activity ``splits`` payload the legacy "build everything then
    discard" path produced. Pinning this ensures the page-only filter
    didn't drop a row that belonged to a kept activity.
    """
    from api.packs import get_history_pack

    ctx = _ctx(db_with_seeded_user)
    full = get_history_pack(ctx)
    paged = get_history_pack(ctx, limit=5, offset=0)

    # The first 5 entries of the full list (sorted date-desc) should
    # equal the page-1 entries field-for-field, including each one's
    # splits.
    for full_act, paged_act in zip(full["activities"][:5], paged["activities"]):
        assert paged_act == full_act


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


def _count_load_data_from_db(monkeypatch) -> dict:
    """Patch ``load_data_from_db`` everywhere it can be reached and
    return a {'n': int} call counter.

    Patching only ``api.packs.load_data_from_db`` (the eager top-level
    import) misses lazy ``from analysis.data_loader import load_data_from_db``
    statements buried inside ``_compute_threshold_data`` and
    ``_build_threshold_trend_chart``. Those lazy imports resolve against
    ``analysis.data_loader`` at call time, so a future regression that
    reintroduced a re-load via the deps.py path would slip past a single-
    site patch. Patch both modules so any code path counts.
    """
    from api import packs as packs_mod
    import analysis.data_loader as loader_mod

    real_loader = loader_mod.load_data_from_db
    calls = {"n": 0}

    def counting_loader(uid, _db):
        calls["n"] += 1
        return real_loader(uid, _db)

    monkeypatch.setattr(loader_mod, "load_data_from_db", counting_loader)
    monkeypatch.setattr(packs_mod, "load_data_from_db", counting_loader)
    return calls


@pytest.mark.parametrize("training_base", ["hr", "pace"])
def test_threshold_helpers_dont_reload_on_hr_pace_base(
    db_with_seeded_user, monkeypatch, training_base,
):
    """``_compute_threshold_data`` and ``_build_threshold_trend_chart``
    used to call ``load_data_from_db`` a second time inside the request
    on HR/pace base — bypassing ``RequestContext._data`` and paying for
    a full re-load of activities + splits + recovery + fitness + plan
    just to read the wide-fitness frame they already had upstream.

    With ``fitness_data`` threaded through both helpers, this regression
    is silenced. The test exercises both ``threshold_data`` and
    ``cp_trend_chart`` cached_properties (the two consumers) and asserts
    the loader still runs exactly once.
    """
    from db.models import UserConfig as UserConfigModel

    db, user_id = db_with_seeded_user
    db.add(UserConfigModel(user_id=user_id, training_base=training_base))
    db.commit()

    calls = _count_load_data_from_db(monkeypatch)

    from api import packs as packs_mod
    ctx = packs_mod.RequestContext(user_id=user_id, db=db)
    _ = ctx.threshold_data
    _ = ctx.cp_trend_chart

    assert calls["n"] == 1, (
        f"expected loader to run exactly once per request on "
        f"training_base={training_base!r}, got {calls['n']}"
    )


@pytest.mark.parametrize("training_base", ["hr", "pace"])
def test_get_dashboard_data_does_not_double_load_on_hr_pace_base(
    db_with_seeded_user, monkeypatch, training_base,
):
    """The legacy ``get_dashboard_data`` path (still wired in for CLI /
    skill scripts and a handful of tests) ran the threshold helpers with
    the same pre-fix double-load pattern. Cover it explicitly so the
    fallback path can't silently regress.
    """
    from db.models import UserConfig as UserConfigModel

    db, user_id = db_with_seeded_user
    db.add(UserConfigModel(user_id=user_id, training_base=training_base))
    db.commit()

    calls = _count_load_data_from_db(monkeypatch)

    from api.deps import get_dashboard_data
    get_dashboard_data(user_id=user_id, db=db)

    assert calls["n"] == 1, (
        f"get_dashboard_data on training_base={training_base!r} ran the "
        f"loader {calls['n']} times — expected 1."
    )


def test_today_route_payload_includes_as_of_date(db_with_seeded_user):
    """The /api/today payload must carry the server-local calendar date.

    Clients render the eyebrow against this rather than `new Date()` so a
    traveler whose device clock crossed midnight before sync caught up
    doesn't see the page assert a date the server hasn't reached. The
    field must be an ISO `YYYY-MM-DD` string equal to the server's
    current `date.today()`.
    """
    from api.routes.today import _build_today_payload

    db, user_id = db_with_seeded_user
    payload = _build_today_payload(user_id, db)

    assert "as_of_date" in payload
    assert payload["as_of_date"] == date.today().isoformat()


def test_today_route_payload_includes_data_as_of(db_with_seeded_user):
    """The /api/today payload must carry an ISO datetime anchoring page
    staleness. The signal must come from the actual data — not the sync
    attempt time — so a sync that pulled no new rows correctly leaves
    the value alone and the banner stays up.

    Composition is `max(insight.generated_at, recovery latest_date EOD,
    last activity date EOD)`. With seeded activities and recovery rows
    but no AiInsight, the value should be EOD on the latest seeded date.
    """
    from api.routes.today import _build_today_payload

    db, user_id = db_with_seeded_user
    payload = _build_today_payload(user_id, db)

    assert "data_as_of" in payload
    assert payload["data_as_of"] is not None
    # Seeded activities + recovery extend through `today - 1` (the loop
    # writes i=0..13 against `today - timedelta(days=14 - i)`), so the
    # latest data row is yesterday's date. With no AiInsight row, the
    # anchor is yesterday at noon UTC. Noon UTC is the symmetry point
    # for date-only rows so a single row dated D appears as local-date
    # D for every realistic timezone (±12h from UTC).
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert payload["data_as_of"] == f"{yesterday}T12:00:00Z"


def test_data_as_of_uses_insight_generated_at_when_newest(db_with_seeded_user):
    """When an AiInsight row exists and is newer than the latest data
    rows, its generated_at is the anchor. This is the common steady
    state — post-sync, the runner regenerates the brief, which advances
    the timestamp past the noon-UTC date anchors that the recovery and
    activity rows produce.

    The fixture seeds activity/recovery rows ending at ``today - 1``,
    which anchor at ``yesterday T12:00:00Z``. We pick a timestamp
    strictly later than that (``today T03:00:00`` — past noon UTC of
    yesterday) so the assertion can't tie on insertion order inside
    ``max()``.
    """
    from datetime import datetime, time
    from api.routes.today import _build_today_payload
    from db.models import AiInsight

    db, user_id = db_with_seeded_user
    fixed = datetime.combine(date.today(), time(3, 0, 0))
    db.add(AiInsight(
        user_id=user_id,
        insight_type="daily_brief",
        headline="t",
        summary="t",
        findings=[],
        recommendations=[],
        generated_at=fixed,
    ))
    db.commit()

    payload = _build_today_payload(user_id, db)
    # Server normalizes naive UTC datetimes to ISO + trailing `Z` so the
    # browser doesn't re-interpret as local time at the day boundary.
    assert payload["data_as_of"] == fixed.isoformat() + "Z"


def test_data_as_of_uses_noon_utc_for_date_only_rows(db_with_seeded_user):
    """Date-only rows (recovery, activity) MUST anchor at ``T12:00:00Z``,
    not start-of-day or end-of-day.

    Why this matters: a row dated ``2026-05-02`` represents a calendar
    day in some real-world timezone, but the row's storage layer doesn't
    record which one. End-of-day UTC would push the row's local date
    forward by up to 14 hours — a Beijing user (UTC+8) would see
    yesterday's row as today's. Start-of-day breaks symmetrically for
    Pacific users. Noon UTC is the symmetry point: ±12 hours from any
    realistic timezone, the row's local date is preserved.

    The assertion is exact, not just startswith, so a future tweak to
    23:59 / 00:00 / arbitrary noon-adjacent time fails loudly.
    """
    from api.routes.today import _build_today_payload
    db, user_id = db_with_seeded_user
    payload = _build_today_payload(user_id, db)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert payload["data_as_of"] == f"{yesterday}T12:00:00Z"


def test_data_as_of_is_none_with_no_data(monkeypatch):
    """Fresh user with no data anywhere — data_as_of is null and the
    frontend suppresses the banner (nothing to anchor on)."""
    import tempfile

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

    from db.models import User
    user_id = "fresh-user"
    db = db_session.SessionLocal()
    db.add(User(id=user_id, email="fresh@example.com", hashed_password="x"))
    db.commit()

    from api.routes.today import _build_today_payload
    payload = _build_today_payload(user_id, db)
    assert payload["data_as_of"] is None
    db.close()


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
