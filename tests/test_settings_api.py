"""Integration tests for the /api/settings PUT endpoint validation.

Covers the scheduler-interval validation wired in api/routes/settings.py:
the unit-level normalize is tested in test_sync_scheduler.py; this file
proves the API translates a ValueError into a structured 400 response and
that the settings GET surfaces the allowed-options contract the UI depends on.
"""
import os
import tempfile

import pytest


@pytest.fixture
def api_client(monkeypatch):
    """Yield a FastAPI TestClient pointing at a fresh, isolated SQLite DB."""
    from fastapi.testclient import TestClient

    # ignore_cleanup_errors lets Windows clean up even if SQLite hasn't
    # released the file lock by the time the temp dir is removed.
    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    monkeypatch.setenv("DATA_DIR", tmpdir.name)
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "false")
    monkeypatch.setenv(
        "PRAXYS_LOCAL_ENCRYPTION_KEY", "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o="
    )
    # Reset the module-level engine singletons so init_db rebuilds against tmpdir.
    from db import session as db_session
    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    from api.main import app
    from api.auth import require_write_access, get_data_user_id
    from db.session import get_db

    test_user_id = "test-user-settings-api"

    def _override_user():
        return test_user_id

    def _override_db():
        db = db_session.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[require_write_access] = _override_user
    app.dependency_overrides[get_data_user_id] = _override_user
    app.dependency_overrides[get_db] = _override_db

    client = TestClient(app)
    try:
        yield client, test_user_id
    finally:
        app.dependency_overrides.clear()
        # Dispose engines so SQLite releases the file before tmpdir cleanup
        # (Windows can't unlink a file held by an open connection pool).
        if db_session.engine is not None:
            db_session.engine.dispose()
        if db_session.async_engine is not None:
            import asyncio
            try:
                asyncio.run(db_session.async_engine.dispose())
            except RuntimeError:
                pass
        db_session.engine = None
        db_session.SessionLocal = None
        db_session.async_engine = None
        db_session.AsyncSessionLocal = None
        tmpdir.cleanup()


def test_put_settings_rejects_invalid_sync_interval(api_client):
    """An invalid sync_interval_hours must return 400 with the validator's message."""
    client, _ = api_client
    res = client.put("/api/settings", json={"source_options": {"sync_interval_hours": 3}})
    assert res.status_code == 400, res.text
    detail = res.json().get("detail", "")
    assert "interval" in detail.lower()
    assert "(6, 12, 24)" in detail


def test_put_settings_accepts_allowed_sync_interval(api_client):
    """An allowed sync_interval_hours must persist and round-trip via GET."""
    client, _ = api_client
    res = client.put("/api/settings", json={"source_options": {"sync_interval_hours": 12}})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "ok"
    assert body["config"]["source_options"]["sync_interval_hours"] == 12

    got = client.get("/api/settings")
    assert got.status_code == 200, got.text
    got_body = got.json()
    assert got_body["config"]["source_options"]["sync_interval_hours"] == 12


def test_get_settings_exposes_sync_interval_options(api_client):
    """GET /api/settings must expose the option list the Settings UI dropdown consumes."""
    client, _ = api_client
    res = client.get("/api/settings")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sync_interval_options_hours"] == [6, 12, 24]
    assert body["default_sync_interval_hours"] == 6


# --- Threshold source selection (clean-break: no manual overrides) ---


def _seed_cp_rows(user_id: str):
    """Insert two cp_estimate rows from different sources for the test user."""
    from datetime import date, timedelta

    from db import session as db_session
    from db.models import FitnessData
    db = db_session.SessionLocal()
    try:
        today = date.today()
        db.add(FitnessData(
            user_id=user_id, date=today,
            metric_type="cp_estimate", value=350.0, source="garmin",
        ))
        db.add(FitnessData(
            user_id=user_id, date=today - timedelta(days=3),
            metric_type="cp_estimate", value=265.0, source="stryd",
        ))
        db.commit()
    finally:
        db.close()


def test_settings_roundtrip_threshold_source_preference(api_client):
    """Integration: PUT preferences.threshold_sources survives GET and flows
    through to effective_thresholds.origin. Guards the whole source-selection
    contract the frontend relies on — the Pydantic widening that lets the
    nested dict through, the resolver source preference, the response shape.
    """
    client, user_id = api_client
    _seed_cp_rows(user_id)

    # Baseline: latest-by-date wins → Garmin (newer) → 350.
    res = client.get("/api/settings")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["effective_thresholds"]["cp_watts"]["value"] == 350.0
    assert body["effective_thresholds"]["cp_watts"]["origin"] == "auto (garmin)"
    # options[] must include both sources.
    opts = {o["source"] for o in body["detected_thresholds"]["cp_watts"]["options"]}
    assert opts == {"garmin", "stryd"}

    # Pick Stryd via preferences.threshold_sources.
    put = client.put(
        "/api/settings",
        json={"preferences": {"threshold_sources": {"cp_estimate": "stryd"}}},
    )
    assert put.status_code == 200, put.text

    got = client.get("/api/settings").json()
    assert got["config"]["preferences"]["threshold_sources"]["cp_estimate"] == "stryd"
    # Resolver now picks Stryd's value even though Garmin's row is newer.
    assert got["effective_thresholds"]["cp_watts"]["value"] == 265.0
    assert got["effective_thresholds"]["cp_watts"]["origin"] == "auto (stryd)"


def test_settings_activity_source_defaults_threshold_source(api_client):
    """If no explicit threshold_sources set, the activity-source preference
    drives CP selection."""
    client, user_id = api_client
    _seed_cp_rows(user_id)

    client.put("/api/settings", json={"preferences": {"activities": "stryd"}})
    got = client.get("/api/settings").json()
    assert got["effective_thresholds"]["cp_watts"]["value"] == 265.0
    assert got["effective_thresholds"]["cp_watts"]["origin"] == "auto (stryd)"


def test_put_settings_discards_legacy_thresholds_body(api_client, caplog):
    """Regression lock: sending thresholds.cp_watts must not persist as a
    manual override. The server accepts the payload for API compat and logs
    that it was ignored, but nothing reaches config.thresholds."""
    import logging
    client, user_id = api_client
    _seed_cp_rows(user_id)

    with caplog.at_level(logging.INFO, logger="api.routes.settings"):
        res = client.put(
            "/api/settings",
            json={"thresholds": {"cp_watts": 999, "lthr_bpm": 888}},
        )
    assert res.status_code == 200, res.text

    got = client.get("/api/settings").json()
    # config.thresholds didn't receive the values.
    stored = got["config"].get("thresholds") or {}
    assert "cp_watts" not in stored or not stored.get("cp_watts")
    assert "lthr_bpm" not in stored or not stored.get("lthr_bpm")
    # effective CP should still come from the seed data, not the bogus 999.
    assert got["effective_thresholds"]["cp_watts"]["value"] == 350.0
    # Discard was logged so the next maintainer can spot old clients.
    assert any(
        "discarding legacy thresholds" in rec.getMessage() for rec in caplog.records
    )


def test_detect_thresholds_options_deduped_and_date_sorted(api_client):
    """_detect_thresholds_from_db contract: one entry per source, sorted
    date-desc, with the newest-per-source value chosen when a source has
    multiple rows."""
    from datetime import date, timedelta

    from api.routes.settings import _detect_thresholds_from_db
    from db import session as db_session
    from db.models import FitnessData

    _, user_id = api_client
    db = db_session.SessionLocal()
    today = date.today()
    try:
        # Two Stryd rows (older should lose to newer), plus one Garmin.
        db.add(FitnessData(
            user_id=user_id, date=today - timedelta(days=10),
            metric_type="cp_estimate", value=255.0, source="stryd",
        ))
        db.add(FitnessData(
            user_id=user_id, date=today - timedelta(days=1),
            metric_type="cp_estimate", value=265.0, source="stryd",
        ))
        db.add(FitnessData(
            user_id=user_id, date=today - timedelta(days=4),
            metric_type="cp_estimate", value=350.0, source="garmin",
        ))
        db.commit()
        detected = _detect_thresholds_from_db(user_id, db)
    finally:
        db.close()

    opts = detected["cp_watts"]["options"]
    assert len(opts) == 2, "one entry per source, not per row"
    # Sorted date-desc — Stryd's newer row wins over Garmin.
    assert [o["source"] for o in opts] == ["stryd", "garmin"]
    assert opts[0]["value"] == 265.0  # Stryd's newest, not the older 255.
    assert opts[1]["value"] == 350.0
