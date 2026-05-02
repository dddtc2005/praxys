"""Round-trip tests for ``/api/insights`` POST + GET, focused on the
``translations`` field added for issue #103.
"""
from __future__ import annotations

import tempfile

import pytest


@pytest.fixture
def insights_client(monkeypatch):
    """TestClient with a seeded user and JWT auth dependency-overridden."""
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
    from db.models import User

    user_id = "test-user-insights"
    db = db_session.SessionLocal()
    try:
        db.add(User(id=user_id, email="insights@example.com", hashed_password="x"))
        db.commit()
    finally:
        db.close()

    app.dependency_overrides[get_data_user_id] = lambda: user_id
    app.dependency_overrides[require_write_access] = lambda: user_id

    yield TestClient(app)

    app.dependency_overrides.clear()
    tmpdir.cleanup()


def test_post_get_round_trip_with_translations(insights_client):
    body = {
        "insight_type": "daily_brief",
        "headline": "Today: easy run",
        "summary": "HRV up; TSB +5.",
        "findings": [{"type": "positive", "text": "HRV trending up"}],
        "recommendations": ["Run easy"],
        "meta": {"dataset_hash": "abc123"},
        "translations": {
            "zh": {
                "headline": "今日：轻松跑",
                "summary": "HRV 上升；TSB +5。",
                "findings": [{"type": "positive", "text": "HRV 趋势上升"}],
                "recommendations": ["轻松跑"],
            }
        },
    }
    r = insights_client.post("/api/insights", json=body)
    assert r.status_code == 200, r.text

    r = insights_client.get("/api/insights/daily_brief")
    assert r.status_code == 200
    payload = r.json()["insight"]
    assert payload["headline"] == "Today: easy run"
    assert payload["translations"]["zh"]["headline"] == "今日：轻松跑"
    assert payload["meta"]["dataset_hash"] == "abc123"


def test_get_returns_empty_translations_when_legacy_row(insights_client):
    """Old rows pushed without translations should still serialize cleanly."""
    body = {
        "insight_type": "training_review",
        "headline": "Volume up",
        "summary": "Strong week.",
        "findings": [],
        "recommendations": [],
        # no 'translations' field — defaults to empty dict via Pydantic.
    }
    r = insights_client.post("/api/insights", json=body)
    assert r.status_code == 200

    r = insights_client.get("/api/insights/training_review")
    payload = r.json()["insight"]
    assert payload["translations"] == {}
