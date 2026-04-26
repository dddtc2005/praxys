"""ETag/304 revalidation tests (issue #147 / L2).

Covers the wire-level contract a browser client depends on:

  * Cold visit returns 200 with an ``ETag`` and ``Cache-Control``.
  * Warm visit with matching ``If-None-Match`` returns 304 and no body.
  * After a write that bumps a relevant scope, the ETag changes (so the
    304 short-circuit doesn't leak stale data after sync).
  * Per-pack scope isolation — a goal/config edit doesn't bust the
    History page's ETag, a plan write doesn't bust /api/science.
  * History's pagination salt: different ``offset`` values produce
    different ETags at the same revision state.

These tests use FastAPI dependency overrides instead of minting JWTs so
they exercise the full route → ETag dependency → guard pipeline without
the rate-limited auth surface in the way.
"""
from __future__ import annotations

import asyncio
import tempfile
from datetime import date, timedelta

import pytest


@pytest.fixture
def etag_client(monkeypatch):
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
    from db.models import (
        Activity,
        ActivitySplit,
        FitnessData,
        RecoveryData,
        TrainingPlan,
        User,
    )
    from db.session import get_db

    user_id = "test-user-etag"

    db = db_session.SessionLocal()
    try:
        db.add(User(id=user_id, email="etag@example.com", hashed_password="x"))
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
# Pure-function tests (no FastAPI)
# ---------------------------------------------------------------------------


def test_compute_etag_is_deterministic_and_short(etag_client):
    """Same revisions → same ETag bytes; output is short, weakly quoted."""
    from api.etag import compute_etag, ENDPOINT_SCOPES
    from db import session as db_session

    _, user_id = etag_client
    db = db_session.SessionLocal()
    try:
        a = compute_etag(db, user_id, ENDPOINT_SCOPES["today"])
        b = compute_etag(db, user_id, ENDPOINT_SCOPES["today"])
        assert a == b, "ETag must be deterministic for the same scope state"
        assert a.startswith('W/"') and a.endswith('"')
        # blake2b(digest_size=8) → 16 hex chars + 4 quoting overhead = 20.
        assert len(a) == 20, f"ETag should be compact (got {a!r})"
    finally:
        db.close()


def test_bump_revisions_changes_etag(etag_client):
    """Bumping any scope used by the endpoint must change its ETag."""
    from api.etag import compute_etag, ENDPOINT_SCOPES
    from db.cache_revision import bump_revisions
    from db import session as db_session

    _, user_id = etag_client
    db = db_session.SessionLocal()
    try:
        before = compute_etag(db, user_id, ENDPOINT_SCOPES["today"])
        bump_revisions(db, user_id, ["activities"])
        db.commit()
        after = compute_etag(db, user_id, ENDPOINT_SCOPES["today"])
        assert before != after
    finally:
        db.close()


def test_scope_isolation_history_vs_goal(etag_client):
    """History reads activities/splits/config — a goal-only edit (config) DOES
    bust both, but a plans-only bump must not bust History.

    The strict isolation we care about: writes to scopes a pack does NOT read
    must not invalidate that pack's cache. ``plans`` is read by today/training/
    goal but NOT by history or science.
    """
    from api.etag import compute_etag, ENDPOINT_SCOPES
    from db.cache_revision import bump_revisions
    from db import session as db_session

    _, user_id = etag_client
    db = db_session.SessionLocal()
    try:
        history_before = compute_etag(db, user_id, ENDPOINT_SCOPES["history"])
        science_before = compute_etag(db, user_id, ENDPOINT_SCOPES["science"])
        today_before = compute_etag(db, user_id, ENDPOINT_SCOPES["today"])

        bump_revisions(db, user_id, ["plans"])
        db.commit()

        # plans is in /today's scope set → ETag flips
        assert compute_etag(db, user_id, ENDPOINT_SCOPES["today"]) != today_before
        # plans is NOT in history's or science's scopes → ETags stable
        assert compute_etag(db, user_id, ENDPOINT_SCOPES["history"]) == history_before
        assert compute_etag(db, user_id, ENDPOINT_SCOPES["science"]) == science_before
    finally:
        db.close()


def test_etag_guard_match_strict_and_list_form():
    """ETagGuard matches both bare and comma-separated If-None-Match values."""
    from api.etag import ETagGuard

    etag = 'W/"abcdef0123456789"'
    assert ETagGuard(etag, etag).is_match
    # Some proxies strip the W/ prefix.
    assert ETagGuard(etag, etag.removeprefix("W/")).is_match
    # RFC 7232 §3.2 list form.
    assert ETagGuard(etag, f'"other", {etag}').is_match
    # RFC 7232 §3.2: ``*`` matches any representation.
    assert ETagGuard(etag, "*").is_match
    # Empty / mismatched headers don't match.
    assert not ETagGuard(etag, "").is_match
    assert not ETagGuard(etag, 'W/"different"').is_match


def test_compute_etag_salt_distinguishes_pages(etag_client):
    """History's ?offset=0 and ?offset=20 must hash to different ETags."""
    from api.etag import compute_etag, ENDPOINT_SCOPES
    from db import session as db_session

    _, user_id = etag_client
    db = db_session.SessionLocal()
    try:
        page0 = compute_etag(
            db, user_id, ENDPOINT_SCOPES["history"],
            salt="limit=20&offset=0&source=",
        )
        page1 = compute_etag(
            db, user_id, ENDPOINT_SCOPES["history"],
            salt="limit=20&offset=20&source=",
        )
        assert page0 != page1
    finally:
        db.close()


# ---------------------------------------------------------------------------
# End-to-end via TestClient
# ---------------------------------------------------------------------------


def test_today_cold_then_304_warm(etag_client):
    """Cold visit returns 200 + ETag; warm visit with matching tag returns 304."""
    client, _ = etag_client

    cold = client.get("/api/today")
    assert cold.status_code == 200
    etag = cold.headers.get("etag")
    assert etag and etag.startswith('W/"')
    assert "private" in cold.headers.get("cache-control", "").lower()
    assert cold.json()  # body present

    warm = client.get("/api/today", headers={"If-None-Match": etag})
    assert warm.status_code == 304
    assert warm.content == b""
    # 304 must echo the ETag so the browser keeps the cached copy keyed.
    assert warm.headers.get("etag") == etag


def test_today_etag_changes_after_relevant_write(etag_client):
    """A new activity (sync_writer.write_activities) busts /today's ETag,
    a science-only edit doesn't bust /history."""
    from db.cache_revision import bump_revisions
    from db import session as db_session

    client, user_id = etag_client

    # Capture the cold ETags for two endpoints with disjoint scope sets.
    today_cold = client.get("/api/today")
    history_cold = client.get("/api/history?limit=5")
    today_etag = today_cold.headers["etag"]
    history_etag = history_cold.headers["etag"]

    # Simulate a sync writing a new activity row → bump_revisions("activities")
    db = db_session.SessionLocal()
    try:
        bump_revisions(db, user_id, ["activities"])
        db.commit()
    finally:
        db.close()

    # /today must now miss the previous tag …
    today_after = client.get(
        "/api/today", headers={"If-None-Match": today_etag},
    )
    assert today_after.status_code == 200
    assert today_after.headers["etag"] != today_etag
    # … but /history reads activities too, so it ALSO busts. The pack-aware
    # win shows up on /science (config-only). Verify that next.
    science_cold = client.get("/api/science")
    science_etag = science_cold.headers["etag"]

    db = db_session.SessionLocal()
    try:
        bump_revisions(db, user_id, ["activities"])
        db.commit()
    finally:
        db.close()

    # /science is config-only; an activities bump must NOT change its ETag.
    science_warm = client.get(
        "/api/science", headers={"If-None-Match": science_etag},
    )
    assert science_warm.status_code == 304


def test_history_pagination_isolated_etags(etag_client):
    """Different ?offset values produce different ETags at the same DB state.

    Without the salt, page-2 would 304 against a page-1 cache and replay the
    wrong rows. This is the regression that test guards against.
    """
    client, _ = etag_client

    p0 = client.get("/api/history?limit=5&offset=0")
    p1 = client.get("/api/history?limit=5&offset=5")
    assert p0.status_code == 200
    assert p1.status_code == 200
    assert p0.headers["etag"] != p1.headers["etag"]

    # Crossing them should NOT match.
    cross = client.get(
        "/api/history?limit=5&offset=5",
        headers={"If-None-Match": p0.headers["etag"]},
    )
    assert cross.status_code == 200


def test_bump_savepoint_preserves_pending_writes(etag_client):
    """A first-time bump that races a concurrent insert must not roll back
    the activity rows the caller staged in the same transaction.

    Reproduces the bug C1 from PR-157 review: prior code called
    ``db.rollback()`` on IntegrityError, discarding every pending row in the
    unit of work. The fix wraps the INSERT in ``begin_nested()`` so the
    rollback is scoped to the savepoint.
    """
    from datetime import date as _date
    from db import session as db_session
    from db.cache_revision import bump_revisions
    from db.models import Activity, CacheRevision

    _, user_id = etag_client

    # Pre-create the (user_id, "activities") row in a side session — this is
    # the concurrent-worker scenario the real bug needed.
    side = db_session.SessionLocal()
    try:
        side.add(CacheRevision(user_id=user_id, scope="activities", revision=99))
        side.commit()
    finally:
        side.close()

    main = db_session.SessionLocal()
    try:
        # Stage an activity row, then call bump — the bump's INSERT will hit
        # the unique-constraint, the savepoint must roll back ONLY itself.
        new_act = Activity(
            user_id=user_id, activity_id="savepoint-test",
            date=_date.today(), activity_type="running", source="garmin",
        )
        main.add(new_act)
        bump_revisions(main, user_id, ["activities"])
        main.commit()

        # The activity must still exist (proves the rollback was scoped).
        survived = main.query(Activity).filter(
            Activity.activity_id == "savepoint-test"
        ).first()
        assert survived is not None, "savepoint should have preserved Activity insert"

        # And the revision must have advanced from the pre-seeded 99.
        rev = main.query(CacheRevision).filter(
            CacheRevision.user_id == user_id,
            CacheRevision.scope == "activities",
        ).first()
        assert rev.revision == 100
    finally:
        main.close()


def test_today_etag_changes_at_midnight(etag_client, monkeypatch):
    """At midnight the time-windowed endpoints must hand out a new ETag even
    with zero DB writes — otherwise a 304 would replay yesterday's framing
    (current week, race countdown, "next 7 days" upcoming).
    """
    from api import etag as etag_mod

    client, _ = etag_client

    # Pin "today" to a known date, then advance it by one day.
    class _FrozenDate:
        _value = "2026-04-26"

        @classmethod
        def today(cls):
            from datetime import date as _real_date
            return _real_date.fromisoformat(cls._value)

    monkeypatch.setattr(etag_mod, "date", _FrozenDate)
    cold = client.get("/api/today")
    yesterday_etag = cold.headers["etag"]
    assert cold.status_code == 200

    # Same DB state, but a new calendar day → guard salt flips → different ETag.
    _FrozenDate._value = "2026-04-27"
    next_day = client.get(
        "/api/today", headers={"If-None-Match": yesterday_etag},
    )
    assert next_day.status_code == 200, "midnight rollover must NOT 304"
    assert next_day.headers["etag"] != yesterday_etag

    # /science doesn't depend on date.today(), so it should not flip on the
    # day boundary alone.
    _FrozenDate._value = "2026-04-26"
    science_cold = client.get("/api/science")
    science_etag = science_cold.headers["etag"]
    _FrozenDate._value = "2026-04-27"
    science_warm = client.get(
        "/api/science", headers={"If-None-Match": science_etag},
    )
    assert science_warm.status_code == 304


def test_settings_put_busts_today_etag(etag_client):
    """A PUT /api/settings should invalidate every endpoint's ETag because
    config is in everyone's scope set. Guards against forgetting to bump
    config on a future settings refactor.
    """
    client, _ = etag_client

    cold = client.get("/api/today")
    today_etag = cold.headers["etag"]

    # Touch the user's display name — minimal, non-disruptive change.
    r = client.put("/api/settings", json={"display_name": "etag-test"})
    assert r.status_code == 200

    warm = client.get(
        "/api/today", headers={"If-None-Match": today_etag},
    )
    assert warm.status_code == 200
    assert warm.headers["etag"] != today_etag
