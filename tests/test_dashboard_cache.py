"""Materialised dashboard cache tests (issue #148 / L3).

Covers the contract a deployed L3 cache layer must satisfy:

  * Cold visit returns 200, populates the cache, and bumps the miss
    counter.
  * Warm visit returns 200 with byte-identical body, served from the
    cache (verbatim bytes via ``Response(media_type="application/json")``,
    no FastAPI re-encoding pass), bumping the hit counter.
  * Settings/goal edit invalidates the cache (acceptance criterion in
    #148): the next visit reads fresh data, NOT the stale cache row.
  * Stale-cache detection: a cache row tagged with an older
    ``source_version`` is detected on read, falls through to compute,
    returns the correct fresh value, and overwrites the stale row.
  * Race-during-compute (the actual race-correctness invariant from
    #148): when a write commits *while compute is running*, the cache
    row gets tagged with the *pre-compute* snapshot — so the next
    reader sees fresh revisions, mismatches, and recomputes.
  * Date salt: at midnight the time-windowed sections (today/training/
    goal) recompute even with zero DB writes — same axis as the L2 ETag.
  * Per-section scope isolation: a write to a scope NOT in the section's
    SECTION_SCOPES leaves the cache valid (no spurious recompute).
  * Defensive: a corrupt cached payload triggers recompute AND deletes
    the corrupt row, never an HTTP 500 and never a recurring
    corrupt-row replay loop.
  * Programmer errors propagate: a typo'd section name raises
    ``KeyError`` at the boundary, not a silent miss-forever.

Tests use FastAPI dependency overrides to skip JWT minting — same
pattern as ``test_etag.py`` — so they exercise the full route → cache
pipeline without the rate-limited auth surface in the way.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import date, timedelta

import pytest


@pytest.fixture
def cache_client(monkeypatch):
    """TestClient + seeded user, with auth dependency-overridden."""
    from fastapi.testclient import TestClient

    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    monkeypatch.setenv("DATA_DIR", tmpdir.name)
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "false")
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

    from api.main import app
    from api.auth import get_data_user_id, require_write_access
    from api.dashboard_cache import reset_stats
    from db.models import (
        Activity,
        ActivitySplit,
        FitnessData,
        RecoveryData,
        TrainingPlan,
        User,
    )
    from db.session import get_db

    user_id = "test-user-cache"

    db = db_session.SessionLocal()
    try:
        db.add(User(id=user_id, email="cache@example.com", hashed_password="x"))
        today = date.today()
        for i in range(7):
            d = today - timedelta(days=7 - i)
            db.add(Activity(
                user_id=user_id, activity_id=f"act-{i}", date=d,
                activity_type="running", distance_km=8.0, duration_sec=2400.0,
                avg_power=240.0, max_power=300.0, avg_hr=150.0, max_hr=170.0,
                cp_estimate=265.0, rss=70.0, source="stryd",
            ))
            db.add(ActivitySplit(
                user_id=user_id, activity_id=f"act-{i}", split_num=1,
                distance_km=4.0, duration_sec=1200.0,
                avg_power=245.0, avg_hr=152.0, avg_pace_min_km="5:00",
            ))
            db.add(RecoveryData(
                user_id=user_id, date=d, sleep_score=80.0, hrv_avg=50.0,
                resting_hr=50.0, readiness_score=75.0, source="oura",
            ))
        db.add(FitnessData(
            user_id=user_id, date=today, metric_type="cp_estimate",
            value=270.0, source="stryd",
        ))
        db.add(TrainingPlan(
            user_id=user_id, date=today, workout_type="tempo",
            planned_duration_min=45, target_power_min=240,
            target_power_max=260, source="stryd",
        ))
        db.commit()
    finally:
        db.close()

    reset_stats()

    def _override_user():
        return user_id

    def _override_db():
        d = db_session.SessionLocal()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_data_user_id] = _override_user
    app.dependency_overrides[require_write_access] = _override_user
    app.dependency_overrides[get_db] = _override_db

    client = TestClient(app)
    try:
        yield client, user_id
    finally:
        app.dependency_overrides.clear()
        if db_session.engine is not None:
            db_session.engine.dispose()
        if db_session.async_engine is not None:
            try:
                asyncio.run(db_session.async_engine.dispose())
            except RuntimeError:
                pass
        db_session.engine = None
        db_session.SessionLocal = None
        db_session.async_engine = None
        db_session.AsyncSessionLocal = None
        tmpdir.cleanup()


# ---------------------------------------------------------------------------
# Pure-function / structural tests
# ---------------------------------------------------------------------------


def test_section_scopes_align_with_etag_endpoint_scopes(cache_client):
    """L3 SECTION_SCOPES must equal L2 ENDPOINT_SCOPES for shared sections,
    AND ``_DATE_SALTED_SECTIONS`` must equal ``_DATE_SALTED_ENDPOINTS`` for
    those sections.

    Why both: the cache hit serves a body that the L2 ETag's 304 path
    must agree on. If L3's invalidation schedule diverges from L2's, a
    304 from one layer combined with a stale read from the other could
    replay yesterday's framing or hide a fresh write.
    """
    from api import dashboard_cache as dc_mod
    from api import etag as etag_mod

    for section, scopes in dc_mod.SECTION_SCOPES.items():
        assert section in etag_mod.ENDPOINT_SCOPES, (
            f"L3 section {section!r} has no matching L2 endpoint"
        )
        l2_scopes = set(etag_mod.ENDPOINT_SCOPES[section])
        l3_scopes = set(scopes)
        assert l3_scopes == l2_scopes, (
            f"L3 scopes {l3_scopes} for {section!r} diverge from L2 "
            f"scopes {l2_scopes} — caching layer would invalidate on a "
            "different schedule than the ETag, producing stale 200s."
        )

    # Date-salt alignment: the two layers must agree on which sections
    # depend on date.today(). Restricted to sections L3 actually caches
    # (history/science aren't cached at L3 today).
    l3_cached = set(dc_mod.SECTION_SCOPES)
    l3_date_salted = dc_mod._DATE_SALTED_SECTIONS & l3_cached
    l2_date_salted = etag_mod._DATE_SALTED_ENDPOINTS & l3_cached
    assert l3_date_salted == l2_date_salted, (
        f"date-salt sets diverge for cached sections: "
        f"L3={l3_date_salted}, L2={l2_date_salted}. A future endpoint "
        "added to one but not the other would produce a 304 path that "
        "replays yesterday's framing or a cache that recomputes while "
        "the ETag stays stale."
    )


def test_compute_source_version_is_deterministic(cache_client):
    """Two calls with no DB writes between them produce the same string,
    sorted alphabetically per the docstring contract."""
    from api.dashboard_cache import compute_source_version
    from db import session as db_session

    _, user_id = cache_client
    db = db_session.SessionLocal()
    try:
        a = compute_source_version(db, user_id, "today")
        b = compute_source_version(db, user_id, "today")
        assert a == b
        # Alphabetical: activities < config < fitness < plans < recovery
        assert a.split("|")[0].startswith("activities="), (
            f"first scope must be 'activities' in alphabetical order, got {a}"
        )
        assert "config=" in a
        assert f"d={date.today().isoformat()}" in a, (
            "today is date-salted — date.today() must appear in source_version"
        )
    finally:
        db.close()


def test_compute_source_version_advances_on_write(cache_client):
    """A bump to a scope in the section's SECTION_SCOPES must change source_version."""
    from api.dashboard_cache import compute_source_version
    from db.cache_revision import bump_revisions
    from db import session as db_session

    _, user_id = cache_client
    db = db_session.SessionLocal()
    try:
        before = compute_source_version(db, user_id, "today")
        bump_revisions(db, user_id, ["activities"])
        db.commit()
        after = compute_source_version(db, user_id, "today")
        assert before != after
    finally:
        db.close()


def test_unknown_section_raises_key_error(cache_client):
    """A typo'd section must raise KeyError at the boundary, not silently
    write an orphan row that's never read back. CHECK constraint at the
    storage layer is the belt; this Python-side raise is the suspenders.
    """
    from api.dashboard_cache import compute_source_version, write_cache
    from db import session as db_session

    _, user_id = cache_client
    db = db_session.SessionLocal()
    try:
        with pytest.raises(KeyError, match="unknown cache section"):
            compute_source_version(db, user_id, "todayy")  # type: ignore[arg-type]
        with pytest.raises(KeyError, match="unknown cache section"):
            write_cache(db, user_id, "scince", "sv", b"{}")  # type: ignore[arg-type]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# End-to-end via TestClient
# ---------------------------------------------------------------------------


def test_today_cold_then_warm_hits_cache(cache_client):
    """Cold visit populates cache (miss), warm visit returns byte-identical
    body from cache (hit). Body equality at the bytes level proves the
    "verbatim bytes return" claim — no drift between hot and cold paths.
    """
    from api.dashboard_cache import get_stats

    client, _ = cache_client

    cold = client.get("/api/today")
    assert cold.status_code == 200
    cold_bytes = cold.content
    assert cold.headers.get("content-type", "").startswith("application/json")
    stats_after_cold = get_stats().get("today", {})
    assert stats_after_cold.get("misses") == 1, "first visit must be a miss"
    assert stats_after_cold.get("hits", 0) == 0

    # Warm visit — TestClient sends no If-None-Match by default, so L2's
    # 304 short-circuit doesn't fire and we exercise the L3 cache layer
    # directly. The 304 path is covered in test_etag.py.
    warm = client.get("/api/today")
    assert warm.status_code == 200
    stats_after_warm = get_stats().get("today", {})
    assert stats_after_warm.get("hits") == 1, "second visit must be a hit"
    assert warm.content == cold_bytes, (
        "cached bytes must equal the freshly-computed bytes — "
        "verbatim-byte hit path"
    )


def test_training_cold_then_warm_hits_cache(cache_client):
    """Direct cold/warm assertion for /api/training, plus scope isolation
    on its unique scope (``splits``): a splits-only bump must invalidate
    /api/training but NOT /api/today (today doesn't read splits).
    """
    from api.dashboard_cache import get_stats, reset_stats
    from db.cache_revision import bump_revisions
    from db import session as db_session

    client, user_id = cache_client
    reset_stats()

    cold = client.get("/api/training")
    assert cold.status_code == 200
    cold_bytes = cold.content

    warm = client.get("/api/training")
    assert warm.status_code == 200
    assert warm.content == cold_bytes
    train_stats = get_stats().get("training", {})
    assert train_stats.get("hits") == 1
    assert train_stats.get("misses") == 1

    # Populate today's cache too so we can later assert it's not invalidated.
    client.get("/api/today")
    reset_stats()

    db = db_session.SessionLocal()
    try:
        bump_revisions(db, user_id, ["splits"])
        db.commit()
    finally:
        db.close()

    # /api/training reads splits → must miss after a splits bump.
    next_training = client.get("/api/training")
    assert next_training.status_code == 200
    train_stats = get_stats().get("training", {})
    assert train_stats.get("misses") == 1, (
        "splits bump must invalidate /api/training (splits is in its scopes)"
    )

    # /api/today does NOT read splits → must still hit.
    next_today = client.get("/api/today")
    assert next_today.status_code == 200
    today_stats = get_stats().get("today", {})
    assert today_stats.get("hits") == 1, (
        "splits bump must NOT invalidate /api/today (splits is not in its scopes)"
    )


def test_settings_edit_invalidates_cache(cache_client):
    """Acceptance criterion: edit settings → next visit gets fresh data.

    The flow: GET /api/today populates the cache. PUT /api/settings bumps
    the ``config`` revision (already wired by L2). The next GET sees a
    mismatched source_version, recomputes, and the new body reflects the
    settings change.
    """
    from api.dashboard_cache import get_stats

    client, _ = cache_client

    cold = client.get("/api/today")
    assert cold.status_code == 200
    cold_training_base = cold.json()["training_base"]

    # Flip training_base to a different valid value so the response visibly differs.
    new_base = "hr" if cold_training_base != "hr" else "pace"
    r = client.put("/api/settings", json={"training_base": new_base})
    assert r.status_code == 200

    after_edit = client.get("/api/today")
    assert after_edit.status_code == 200
    assert after_edit.json()["training_base"] == new_base, (
        "settings edit must invalidate the cache so the next read sees "
        "the new training_base"
    )
    stats = get_stats().get("today", {})
    # The post-edit read must be a miss (config revision advanced).
    assert stats.get("misses", 0) >= 2


def test_goal_edit_invalidates_goal_cache(cache_client):
    """Acceptance criterion (variant): goal edit → /api/goal recomputes."""
    client, _ = cache_client

    cold = client.get("/api/goal")
    assert cold.status_code == 200
    cold_target = (cold.json().get("race_countdown") or {}).get("target_time_sec")

    new_target = (cold_target or 0) + 600  # +10 minutes
    r = client.put("/api/settings", json={"goal": {"target_time_sec": new_target}})
    assert r.status_code == 200

    fresh = client.get("/api/goal")
    assert fresh.status_code == 200
    fresh_target = (fresh.json().get("race_countdown") or {}).get("target_time_sec")
    assert fresh_target == new_target, (
        "goal edit must invalidate the /api/goal cache"
    )


def test_stale_cache_falls_through_to_compute(cache_client):
    """A cache row whose ``source_version`` no longer matches current
    revisions must be detected on read, fall through to compute, return
    the correct fresh value, and overwrite the stale row.

    This is the *post-write detection* test. The race-DURING-compute
    invariant is a separate test below.
    """
    from api.dashboard_cache import compute_source_version
    from db.cache_revision import bump_revisions
    from db.models import DashboardCache
    from db import session as db_session

    client, user_id = cache_client

    cold = client.get("/api/today")
    assert cold.status_code == 200

    # Simulate the wire scenario: hand-write a sentinel into the cache
    # row tagged with the *current* source_version (so it would normally
    # hit), then bump revisions so the snapshot advances past it.
    db = db_session.SessionLocal()
    try:
        row = db.query(DashboardCache).filter(
            DashboardCache.user_id == user_id,
            DashboardCache.section == "today",
        ).first()
        assert row is not None, "cold visit must have populated the cache"
        original_payload = bytes(row.payload_json)
        # Sentinel JSON object — passes the structural sanity check, so
        # it would be served as a cache hit if the staleness logic is
        # broken.
        row.payload_json = json.dumps(
            {"sentinel": "STALE_CACHE_MUST_NOT_LEAK"},
        ).encode("utf-8")
        row.source_version = compute_source_version(db, user_id, "today")
        db.commit()

        # Advance revisions — snapshot for the next read will diverge
        # from the cache row's tag.
        bump_revisions(db, user_id, ["activities"])
        db.commit()
    finally:
        db.close()

    fresh = client.get("/api/today")
    assert fresh.status_code == 200
    body = fresh.json()
    assert "sentinel" not in body, (
        "stale cache row must NOT be served — read must fall through to "
        "compute when source_version mismatches current revisions"
    )

    # And the cache row must now be repopulated with a real payload.
    db = db_session.SessionLocal()
    try:
        row = db.query(DashboardCache).filter(
            DashboardCache.user_id == user_id,
            DashboardCache.section == "today",
        ).first()
        assert row is not None
        new_payload = bytes(row.payload_json)
        assert b"STALE_CACHE_MUST_NOT_LEAK" not in new_payload
        assert len(new_payload) > len(original_payload) // 2, (
            "fresh cache payload should be similar in size to cold-read "
            "payload, not the tiny sentinel dict"
        )
    finally:
        db.close()


def test_race_during_compute_tags_cache_with_pre_compute_snapshot(cache_client):
    """Acceptance criterion from #148: snapshot ``source_version`` BEFORE
    ``compute()`` runs. Even if a write commits *during* compute, the
    cache row gets tagged with the pre-compute snapshot — so the next
    reader sees fresh revisions, mismatches, and recomputes.

    This test exercises ``cached_or_compute`` directly (not via
    TestClient) and fires ``bump_revisions`` *inside* the compute
    callable, simulating a sync_writer commit that lands while a slow
    pack computation is in flight. It then asserts that the persisted
    cache row's ``source_version`` is the PRE-bump value, not the
    post-bump one — the load-bearing invariant a future refactor must
    not break.
    """
    from api.dashboard_cache import (
        cached_or_compute,
        compute_source_version,
        reset_stats,
    )
    from db.cache_revision import bump_revisions
    from db.models import DashboardCache
    from db import session as db_session

    _, user_id = cache_client
    reset_stats()

    request_db = db_session.SessionLocal()
    try:
        pre_bump_sv = compute_source_version(request_db, user_id, "today")

        bumped = []

        def compute_with_concurrent_bump():
            # Simulate a sync_writer commit landing while compute is in flight.
            side = db_session.SessionLocal()
            try:
                bump_revisions(side, user_id, ["activities"])
                side.commit()
                bumped.append(True)
            finally:
                side.close()
            return {"sentinel": "computed_during_concurrent_bump"}

        body = cached_or_compute(
            request_db, user_id, "today",
            compute=compute_with_concurrent_bump,
        )
        assert bumped, "compute callable must have run (cache was empty)"
        assert b"computed_during_concurrent_bump" in body, (
            "first read returns the freshly-computed body bytes"
        )

        # The persisted cache row must be tagged with the PRE-bump
        # snapshot, not the post-bump source_version. If a future
        # refactor moves the snapshot AFTER compute(), this assertion
        # is what catches it.
        check_db = db_session.SessionLocal()
        try:
            row = check_db.query(DashboardCache).filter(
                DashboardCache.user_id == user_id,
                DashboardCache.section == "today",
            ).first()
            assert row is not None, "cache row must have been written"
            assert row.source_version == pre_bump_sv, (
                f"cache row must be tagged with pre-compute snapshot "
                f"({pre_bump_sv!r}), got {row.source_version!r}. The "
                "race-correctness invariant in cached_or_compute is broken — "
                "snapshot was probably moved to AFTER compute()."
            )

            post_bump_sv = compute_source_version(check_db, user_id, "today")
            assert post_bump_sv != pre_bump_sv, (
                "the bump inside compute must have advanced source_version"
            )
        finally:
            check_db.close()
    finally:
        request_db.close()

    # The next read (with current post-bump source_version) must mismatch
    # the cache row's pre_bump_sv tag and recompute fresh data.
    next_db = db_session.SessionLocal()
    try:
        second_body = cached_or_compute(
            next_db, user_id, "today",
            compute=lambda: {"sentinel": "second_compute"},
        )
        assert b"second_compute" in second_body, (
            "second read must miss (post-bump SV ≠ cached SV) and recompute"
        )
    finally:
        next_db.close()


def test_corrupt_cache_payload_recovers_and_deletes_row(cache_client):
    """A corrupt cached payload must trigger recompute (not HTTP 500) AND
    remove the corrupt row so a subsequent write failure can't leave the
    cache stuck in a corrupt-replay loop.

    Defends against a future change to the JSON encoder that could leave
    legacy rows undecodable, and against bit-rot on disk.
    """
    from api.dashboard_cache import compute_source_version
    from db.models import DashboardCache
    from db import session as db_session

    client, user_id = cache_client

    cold = client.get("/api/today")
    assert cold.status_code == 200

    # Corrupt the payload — both invalid UTF-8 and not JSON-shaped.
    db = db_session.SessionLocal()
    try:
        row = db.query(DashboardCache).filter(
            DashboardCache.user_id == user_id,
            DashboardCache.section == "today",
        ).first()
        assert row is not None
        # Keep source_version current so the cache *would* hit if the
        # structural sanity check is missing.
        row.source_version = compute_source_version(db, user_id, "today")
        row.payload_json = b"\x00not-json-at-all\xff"
        db.commit()
    finally:
        db.close()

    after = client.get("/api/today")
    assert after.status_code == 200, (
        "corrupt cache row must recover via recompute, not 500"
    )
    assert "training_base" in after.json(), (
        "recovered response must have the normal /api/today shape"
    )

    # The cache row must now hold a fresh, valid payload (the recompute
    # write) — NOT the original corruption. This proves the corrupt row
    # was removed before the recompute, so a future write failure on the
    # corrupt branch can't leave the row stuck.
    db = db_session.SessionLocal()
    try:
        row = db.query(DashboardCache).filter(
            DashboardCache.user_id == user_id,
            DashboardCache.section == "today",
        ).first()
        assert row is not None, "recompute must have repopulated the row"
        new_body = bytes(row.payload_json)
        assert new_body.startswith(b"{") and new_body.endswith(b"}"), (
            "recovered cache row must hold valid JSON-shaped bytes"
        )
        assert b"\x00not-json-at-all" not in new_body
    finally:
        db.close()


def test_writes_outside_section_scopes_keep_cache_valid(cache_client):
    """Per-section isolation: bumping a scope NOT in /api/goal's scopes
    (which are activities/fitness/config) must NOT invalidate /api/goal.

    ``splits`` is read by /api/training but not /api/goal — this test
    proves L3 doesn't over-invalidate.
    """
    from api.dashboard_cache import get_stats, reset_stats
    from db.cache_revision import bump_revisions
    from db import session as db_session

    client, user_id = cache_client

    client.get("/api/goal")  # populate cache (miss)
    reset_stats()

    db = db_session.SessionLocal()
    try:
        bump_revisions(db, user_id, ["splits"])
        db.commit()
    finally:
        db.close()

    # Second visit must be a hit — splits is not in goal's scopes.
    after = client.get("/api/goal")
    assert after.status_code == 200
    stats = get_stats().get("goal", {})
    assert stats.get("hits") == 1, (
        f"goal cache must survive a splits-only bump (stats={stats})"
    )
    assert stats.get("misses", 0) == 0


def test_today_cache_invalidates_at_midnight(cache_client, monkeypatch):
    """Time-windowed sections must recompute across the date boundary even
    with zero DB writes — same correctness reason as L2's date-salted
    ETag (current week, race countdown, "next 7 days" framing all shift
    at midnight).
    """
    from api import dashboard_cache as dc_mod
    from api.dashboard_cache import get_stats, reset_stats

    client, _ = cache_client

    class _FrozenDate:
        _value = "2026-04-26"

        @classmethod
        def today(cls):
            from datetime import date as _real_date
            return _real_date.fromisoformat(cls._value)

    monkeypatch.setattr(dc_mod, "date", _FrozenDate)

    client.get("/api/today")  # populates cache for 2026-04-26
    reset_stats()

    _FrozenDate._value = "2026-04-27"
    next_day = client.get("/api/today")
    assert next_day.status_code == 200
    stats = get_stats().get("today", {})
    assert stats.get("misses") == 1, (
        f"midnight crossing must produce a miss (stats={stats})"
    )
    assert stats.get("hits", 0) == 0


def test_get_stats_shape_is_typeddict_compatible(cache_client):
    """get_stats() returns a dict whose values match the SectionStats
    TypedDict shape: ``{hits: int, misses: int, ratio: float}``.
    """
    from api.dashboard_cache import SectionStats, get_stats

    client, _ = cache_client
    client.get("/api/today")
    client.get("/api/today")  # produce one miss + one hit

    stats = get_stats()
    assert "today" in stats
    today_stats = stats["today"]
    # SectionStats is a TypedDict — instances are plain dicts at runtime.
    assert set(today_stats.keys()) == set(SectionStats.__annotations__.keys())
    assert isinstance(today_stats["hits"], int)
    assert isinstance(today_stats["misses"], int)
    assert isinstance(today_stats["ratio"], float)
    assert 0.0 <= today_stats["ratio"] <= 1.0
