"""Materialised dashboard cache tests (issue #148 / L3).

Covers the contract a deployed L3 cache layer must satisfy:

  * Cold visit returns 200, populates the cache, and bumps the miss
    counter.
  * Warm visit returns 200 with the same payload, served from the cache,
    bumping the hit counter.
  * Settings/goal edit invalidates the cache (acceptance criterion in
    #148): the next visit reads fresh data, NOT the stale cache row.
  * Race condition: a cache row labelled with an older source_version
    is detected on read, falls through to compute, returns the correct
    fresh value, and overwrites the stale row.
  * Date salt: at midnight the time-windowed sections (today/training/
    goal) recompute even with zero DB writes — same axis as the L2 ETag.
  * Per-section scope isolation: a write to a scope NOT in the section's
    SECTION_SCOPES leaves the cache valid (no spurious recompute).
  * Defensive: a corrupt cached payload triggers recompute, never an
    HTTP 500.

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
# Pure-function tests
# ---------------------------------------------------------------------------


def test_section_scopes_align_with_etag_endpoint_scopes(cache_client):
    """L3 SECTION_SCOPES must be a subset of L2 ENDPOINT_SCOPES for shared
    sections — otherwise a cache row could be valid while the L2 ETag
    has already advanced (the cache hit would serve a body that doesn't
    match the ETag, breaking RFC 7232's idempotence guarantee).
    """
    from api.dashboard_cache import SECTION_SCOPES
    from api.etag import ENDPOINT_SCOPES

    for section, scopes in SECTION_SCOPES.items():
        assert section in ENDPOINT_SCOPES, (
            f"L3 section {section!r} has no matching L2 endpoint"
        )
        l2_scopes = set(ENDPOINT_SCOPES[section])
        l3_scopes = set(scopes)
        assert l3_scopes == l2_scopes, (
            f"L3 scopes {l3_scopes} for {section!r} diverge from L2 "
            f"scopes {l2_scopes} — caching layer would invalidate on a "
            "different schedule than the ETag, producing stale 200s."
        )


def test_compute_source_version_is_deterministic(cache_client):
    """Two calls with no DB writes between them must produce the same string."""
    from api.dashboard_cache import compute_source_version
    from db import session as db_session

    _, user_id = cache_client
    db = db_session.SessionLocal()
    try:
        a = compute_source_version(db, user_id, "today")
        b = compute_source_version(db, user_id, "today")
        assert a == b
        assert "config=" in a, "must include config scope counter"
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


# ---------------------------------------------------------------------------
# End-to-end via TestClient
# ---------------------------------------------------------------------------


def test_today_cold_then_warm_hits_cache(cache_client):
    """Cold visit populates cache (miss), warm visit returns identical body
    from cache (hit). Body equality is the strongest correctness check we
    have — if the cached bytes differ from a recompute, the user sees a
    drift between hot and cold paths.
    """
    from api.dashboard_cache import get_stats

    client, _ = cache_client

    cold = client.get("/api/today")
    assert cold.status_code == 200
    cold_body = cold.json()
    stats_after_cold = get_stats().get("today", {})
    assert stats_after_cold.get("misses") == 1, "first visit must be a miss"
    assert stats_after_cold.get("hits", 0) == 0

    # Warm visit — same ETag would 304 the route, so explicitly skip the
    # If-None-Match path so we exercise the L3 cache layer directly.
    warm = client.get("/api/today")
    assert warm.status_code == 200
    warm_body = warm.json()
    stats_after_warm = get_stats().get("today", {})
    assert stats_after_warm.get("hits") == 1, "second visit must be a hit"
    assert warm_body == cold_body, (
        "cached body must equal the freshly-computed body"
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

    # Flip training_base to a different valid value; api.deps.get_dashboard_data
    # propagates this into ``training_base`` on the response.
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
    """Acceptance criterion (variant): goal edit → /api/goal recomputes.

    /api/goal reads ``activities``, ``fitness``, and ``config``. A goal
    edit (which goes through PUT /api/settings with a goal payload)
    bumps ``config``, so the cache must mismatch and recompute.
    """
    client, _ = cache_client

    cold = client.get("/api/goal")
    assert cold.status_code == 200
    cold_target = (cold.json().get("race_countdown") or {}).get("target_time_sec")

    # Set or change a goal target time so the response visibly differs.
    new_target = (cold_target or 0) + 600  # +10 minutes
    r = client.put("/api/settings", json={"goal": {"target_time_sec": new_target}})
    assert r.status_code == 200

    fresh = client.get("/api/goal")
    assert fresh.status_code == 200
    fresh_target = (fresh.json().get("race_countdown") or {}).get("target_time_sec")
    assert fresh_target == new_target, (
        "goal edit must invalidate the /api/goal cache"
    )


def test_race_condition_falls_through_to_compute(cache_client):
    """Simulate read mid-write: cache row labelled with an older
    source_version must be detected as stale, fall through to compute,
    and return the correct fresh value (acceptance criterion in #148).

    Setup mirrors the wire scenario: a previous request wrote the cache
    tagged with revision N. Before the next read, sync_writer commits
    with revision N+1. The reader's snapshot says N+1; the cache row
    says N. Mismatch → recompute → return fresh.
    """
    from api.dashboard_cache import compute_source_version
    from db.cache_revision import bump_revisions
    from db.models import DashboardCache
    from db import session as db_session

    client, user_id = cache_client

    # Populate the cache with a fresh row.
    cold = client.get("/api/today")
    assert cold.status_code == 200

    # Hand-write a stale source_version into the cache row to simulate
    # the race: the row was written labelled with revisions that have
    # since advanced.
    db = db_session.SessionLocal()
    try:
        row = db.query(DashboardCache).filter(
            DashboardCache.user_id == user_id,
            DashboardCache.section == "today",
        ).first()
        assert row is not None, "cold visit must have populated the cache"
        original_payload = bytes(row.payload_json)
        # Replace payload with a sentinel so we can detect a stale-cache hit
        # if the recompute logic is buggy.
        row.payload_json = json.dumps(
            {"sentinel": "STALE_CACHE_MUST_NOT_LEAK"},
        ).encode("utf-8")
        # Stamp it with the current source_version so it would normally
        # hit. We then bump revisions so the snapshot advances past it.
        row.source_version = compute_source_version(db, user_id, "today")
        db.commit()

        # Advance revisions — simulates a sync_writer commit landing
        # between the previous read and this one.
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

    # And the cache row must now be repopulated with a non-sentinel payload.
    db = db_session.SessionLocal()
    try:
        row = db.query(DashboardCache).filter(
            DashboardCache.user_id == user_id,
            DashboardCache.section == "today",
        ).first()
        assert row is not None
        new_payload = bytes(row.payload_json)
        assert b"STALE_CACHE_MUST_NOT_LEAK" not in new_payload, (
            "post-recompute cache row must hold the fresh payload, "
            "not the sentinel we injected"
        )
        # The fresh row's payload should match the cold-read payload (modulo
        # any non-deterministic fields). At minimum it should not equal the
        # sentinel and should be valid JSON of meaningful size.
        assert len(new_payload) > len(original_payload) // 2, (
            "fresh cache payload should be similar in size to cold-read "
            "payload, not the tiny sentinel dict"
        )
    finally:
        db.close()


def test_corrupt_cache_payload_recovers(cache_client):
    """A corrupt cache row must trigger recompute, never an HTTP 500.

    Defends against a future change to the JSON encoder that could leave
    legacy rows undecodable: the read path logs the corruption and falls
    through to compute, the next write overwrites the row.
    """
    from api.dashboard_cache import compute_source_version
    from db.models import DashboardCache
    from db import session as db_session

    client, user_id = cache_client

    cold = client.get("/api/today")
    assert cold.status_code == 200

    # Corrupt the payload bytes.
    db = db_session.SessionLocal()
    try:
        row = db.query(DashboardCache).filter(
            DashboardCache.user_id == user_id,
            DashboardCache.section == "today",
        ).first()
        assert row is not None
        # Keep source_version current so the cache *would* be considered
        # fresh — only the payload itself is corrupt. Forces the JSON-
        # decode failure branch.
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
