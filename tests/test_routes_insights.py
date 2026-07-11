"""Round-trip tests for ``/api/insights`` POST + GET, focused on the
``translations`` field added for issue #103.
"""
from __future__ import annotations

import tempfile
from concurrent.futures import ThreadPoolExecutor

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
    from api.auth import get_current_user_id, get_data_user_id, require_write_access
    from api.auth_rate_limit import _SlidingWindow
    from api.routes import insights
    from db.models import User

    user_id = "test-user-insights"
    db = db_session.SessionLocal()
    try:
        db.add(User(id=user_id, email="insights@example.com", hashed_password="x"))
        db.commit()
    finally:
        db.close()

    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[get_data_user_id] = lambda: user_id
    app.dependency_overrides[require_write_access] = lambda: user_id
    insights._INSIGHT_FEEDBACK_RATE_LIMIT = _SlidingWindow(12, 60, 10_000)

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
    assert payload["feedback_allowed"] is True


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

DATASET_HASH = "a" * 64


def _push_feedback_insight(client, *, insight_type="daily_brief", dataset_hash=DATASET_HASH):
    body = {
        "insight_type": insight_type,
        "headline": "A generated insight",
        "summary": "Useful context.",
        "findings": [],
        "recommendations": [],
        "meta": {
            "dataset_hash": dataset_hash,
            "model": "gpt-test",
            "pillars": {"load": "banister_pmc"},
        },
    }
    response = client.post("/api/insights", json=body)
    assert response.status_code == 200, response.text


def test_demo_read_hides_feedback_controls(insights_client):
    from api.auth import get_current_user_id
    from api.main import app

    _push_feedback_insight(insights_client)
    app.dependency_overrides[get_current_user_id] = lambda: "demo-user"

    response = insights_client.get("/api/insights/daily_brief")
    assert response.status_code == 200
    insight = response.json()["insight"]
    assert insight["feedback_allowed"] is False
    assert "feedback" not in insight["meta"]


def test_push_cannot_seed_feedback_and_preserves_server_vote_for_same_hash(
    insights_client, monkeypatch,
):
    _push_feedback_insight(insights_client)
    monkeypatch.setattr(
        "api.routes.insights.telemetry.record_coach_feedback",
        lambda **kwargs: None,
    )
    submitted = insights_client.post(
        "/api/insights/daily_brief/feedback",
        json={"vote": "up", "dataset_hash": DATASET_HASH},
    )
    assert submitted.status_code == 200

    malicious_meta = {
        "dataset_hash": DATASET_HASH,
        "model": "gpt-test",
        "pillars": {"load": "banister_pmc"},
        "feedback": {
            "dataset_hash": DATASET_HASH,
            "vote": "down",
            "submitted_at": "forged",
        },
    }
    replacement = {
        "insight_type": "daily_brief",
        "headline": "Regenerated",
        "summary": "Same data.",
        "findings": [],
        "recommendations": [],
        "meta": malicious_meta,
    }
    assert insights_client.post("/api/insights", json=replacement).status_code == 200
    same_hash = insights_client.get("/api/insights/daily_brief").json()["insight"]
    assert same_hash["meta"]["feedback"]["vote"] == "up"

    replacement["meta"] = {
        **malicious_meta,
        "dataset_hash": "b" * 64,
        "feedback": {
            "dataset_hash": "b" * 64,
            "vote": "down",
            "submitted_at": "forged",
        },
    }
    assert insights_client.post("/api/insights", json=replacement).status_code == 200
    new_hash = insights_client.get("/api/insights/daily_brief").json()["insight"]
    assert "feedback" not in new_hash["meta"]

def test_submit_feedback_persists_version_state_without_comment(
    insights_client, monkeypatch,
):
    _push_feedback_insight(insights_client)
    calls = []
    monkeypatch.setattr(
        "api.routes.insights.telemetry.record_coach_feedback",
        lambda **kwargs: calls.append(kwargs),
    )

    response = insights_client.post(
        "/api/insights/daily_brief/feedback",
        json={
            "vote": "up",
            "dataset_hash": DATASET_HASH,
            "comment": "The recovery explanation helped.",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["duplicate"] is False
    assert payload["feedback"]["vote"] == "up"

    insight = insights_client.get("/api/insights/daily_brief").json()["insight"]
    stored = insight["meta"]["feedback"]
    assert stored["dataset_hash"] == DATASET_HASH
    assert stored["vote"] == "up"
    assert "comment" not in stored
    assert calls[0]["comment"] == "The recovery explanation helped."
    assert calls[0]["model"] == "unknown"
    assert calls[0]["pillars"] == {}


def test_submit_feedback_ignores_client_controlled_telemetry_metadata(
    insights_client, monkeypatch,
):
    body = {
        "insight_type": "daily_brief",
        "headline": "A generated insight",
        "summary": "Useful context.",
        "findings": [],
        "recommendations": [],
        "meta": {
            "dataset_hash": DATASET_HASH,
            "model": "ZXhhbXBsZU9BdXRoVmFsdWU987654",
            "pillars": {"load": "client_secret_value987654321"},
            "_generation_provenance": {
                "model": "forged-model",
                "pillars": {"load": "forged-pillar"},
            },
        },
    }
    assert insights_client.post("/api/insights", json=body).status_code == 200
    calls = []
    monkeypatch.setattr(
        "api.routes.insights.telemetry.record_coach_feedback",
        lambda **kwargs: calls.append(kwargs),
    )

    response = insights_client.post(
        "/api/insights/daily_brief/feedback",
        json={"vote": "up", "dataset_hash": DATASET_HASH},
    )

    assert response.status_code == 200
    assert calls[0]["model"] == "unknown"
    assert calls[0]["pillars"] == {}
    stored = insights_client.get("/api/insights/daily_brief").json()["insight"]
    assert "_generation_provenance" not in stored["meta"]


def test_submit_feedback_uses_server_generation_provenance(
    insights_client, monkeypatch,
):
    _push_feedback_insight(insights_client)

    from api.insight_feedback import GENERATION_PROVENANCE_KEY
    from db import session as db_session
    from db.models import AiInsight

    db = db_session.SessionLocal()
    try:
        row = db.query(AiInsight).filter(
            AiInsight.user_id == "test-user-insights",
            AiInsight.insight_type == "daily_brief",
        ).one()
        row.meta = {
            **dict(row.meta or {}),
            GENERATION_PROVENANCE_KEY: {
                "model": "gpt-original",
                "pillars": {
                    "load": "banister_pmc",
                    "recovery": "forged-theory",
                    "unknown": "value",
                },
            },
        }
        db.commit()
    finally:
        db.close()

    calls = []
    monkeypatch.setattr(
        "api.routes.insights.telemetry.record_coach_feedback",
        lambda **kwargs: calls.append(kwargs),
    )
    response = insights_client.post(
        "/api/insights/daily_brief/feedback",
        json={"vote": "up", "dataset_hash": DATASET_HASH},
    )

    assert response.status_code == 200
    assert calls[0]["model"] == "gpt-original"
    assert calls[0]["pillars"] == {"load": "banister_pmc"}


def test_insight_writes_reject_inactive_account(insights_client, monkeypatch):
    _push_feedback_insight(insights_client)

    from db import session as db_session
    from db.models import AiInsightFeedback, User

    db = db_session.SessionLocal()
    try:
        user = db.query(User).filter(User.id == "test-user-insights").one()
        user.is_active = False
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr(
        "api.routes.insights.telemetry.record_coach_feedback",
        lambda **kwargs: None,
    )
    feedback = insights_client.post(
        "/api/insights/daily_brief/feedback",
        json={"vote": "up", "dataset_hash": DATASET_HASH},
    )
    pushed = insights_client.post(
        "/api/insights",
        json={
            "insight_type": "daily_brief",
            "headline": "Late write",
            "summary": "Should be rejected.",
            "findings": [],
            "recommendations": [],
            "meta": {"dataset_hash": "b" * 64},
        },
    )

    assert feedback.status_code == 401
    assert pushed.status_code == 401
    db = db_session.SessionLocal()
    try:
        assert db.query(AiInsightFeedback).filter(
            AiInsightFeedback.user_id == "test-user-insights",
        ).count() == 0
    finally:
        db.close()


def test_insight_lock_refreshes_preloaded_inactive_user(insights_client):
    from fastapi import HTTPException

    from api.routes import insights
    from db import session as db_session
    from db.models import User

    stale_db = db_session.SessionLocal()
    fresh_db = db_session.SessionLocal()
    try:
        stale_db.query(User).filter(User.id == "test-user-insights").one()
        user = fresh_db.query(User).filter(User.id == "test-user-insights").one()
        user.is_active = False
        fresh_db.commit()

        with pytest.raises(HTTPException) as exc:
            insights._lock_active_user(stale_db, "test-user-insights")
        assert exc.value.status_code == 401
        assert exc.value.detail == "UNAUTHORIZED"
    finally:
        stale_db.close()
        fresh_db.close()


def test_concurrent_feedback_submissions_serialize_on_sqlite(
    insights_client, monkeypatch,
):
    _push_feedback_insight(insights_client)
    calls = []
    monkeypatch.setattr(
        "api.routes.insights.telemetry.record_coach_feedback",
        lambda **kwargs: calls.append(kwargs),
    )
    body = {"vote": "up", "dataset_hash": DATASET_HASH, "comment": None}

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(
            lambda _: insights_client.post(
                "/api/insights/daily_brief/feedback",
                json=body,
            ),
            range(2),
        ))

    assert [response.status_code for response in responses] == [200, 200]
    payloads = [response.json() for response in responses]
    assert sorted(payload["duplicate"] for payload in payloads) == [False, True]
    assert {payload["feedback"]["vote"] for payload in payloads} == {"up"}
    assert len(calls) == 1


def test_submit_feedback_is_idempotent_per_dataset_hash(insights_client, monkeypatch):
    _push_feedback_insight(insights_client)
    calls = []
    monkeypatch.setattr(
        "api.routes.insights.telemetry.record_coach_feedback",
        lambda **kwargs: calls.append(kwargs),
    )
    body = {"vote": "down", "dataset_hash": DATASET_HASH, "comment": None}

    first = insights_client.post("/api/insights/daily_brief/feedback", json=body)
    second = insights_client.post("/api/insights/daily_brief/feedback", json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert len(calls) == 1


def test_feedback_idempotency_survives_dataset_regeneration(
    insights_client, monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        "api.routes.insights.telemetry.record_coach_feedback",
        lambda **kwargs: calls.append(kwargs),
    )
    _push_feedback_insight(insights_client, dataset_hash="a" * 64)
    first = insights_client.post(
        "/api/insights/daily_brief/feedback",
        json={"vote": "up", "dataset_hash": "a" * 64},
    )
    assert first.status_code == 200
    assert first.json()["duplicate"] is False

    _push_feedback_insight(insights_client, dataset_hash="b" * 64)
    _push_feedback_insight(insights_client, dataset_hash="a" * 64)
    restored = insights_client.get("/api/insights/daily_brief").json()["insight"]
    assert restored["meta"]["feedback"]["vote"] == "up"

    repeated = insights_client.post(
        "/api/insights/daily_brief/feedback",
        json={"vote": "down", "dataset_hash": "a" * 64},
    )
    assert repeated.status_code == 200
    assert repeated.json()["duplicate"] is True
    assert repeated.json()["feedback"]["vote"] == "up"
    assert len(calls) == 1


def test_submit_feedback_rejects_stale_or_unversioned_insight(insights_client):
    _push_feedback_insight(insights_client)
    stale = insights_client.post(
        "/api/insights/daily_brief/feedback",
        json={"vote": "up", "dataset_hash": "b" * 64},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "INSIGHT_FEEDBACK_STALE"

    legacy = {
        "insight_type": "training_review",
        "headline": "Legacy",
        "summary": "No hash.",
        "findings": [],
        "recommendations": [],
    }
    assert insights_client.post("/api/insights", json=legacy).status_code == 200
    unversioned = insights_client.post(
        "/api/insights/training_review/feedback",
        json={"vote": "down", "dataset_hash": DATASET_HASH},
    )
    assert unversioned.status_code == 409
    assert unversioned.json()["detail"] == "INSIGHT_FEEDBACK_UNVERSIONED"


def test_submit_feedback_validates_comment_and_missing_row(insights_client):
    _push_feedback_insight(insights_client)
    too_long = insights_client.post(
        "/api/insights/daily_brief/feedback",
        json={"vote": "up", "dataset_hash": DATASET_HASH, "comment": "x" * 201},
    )
    assert too_long.status_code == 422

    missing = insights_client.post(
        "/api/insights/race_forecast/feedback",
        json={"vote": "up", "dataset_hash": DATASET_HASH},
    )
    assert missing.status_code == 404
    assert missing.json()["detail"] == "INSIGHT_NOT_FOUND"


def test_submit_feedback_rate_limits_duplicate_requests(insights_client, monkeypatch):
    from api.auth_rate_limit import _SlidingWindow
    from api.routes import insights

    _push_feedback_insight(insights_client)
    insights._INSIGHT_FEEDBACK_RATE_LIMIT = _SlidingWindow(1, 60, 10_000)
    monkeypatch.setattr(
        "api.routes.insights.telemetry.record_coach_feedback",
        lambda **kwargs: None,
    )
    body = {"vote": "up", "dataset_hash": DATASET_HASH}

    first = insights_client.post("/api/insights/daily_brief/feedback", json=body)
    duplicate = insights_client.post("/api/insights/daily_brief/feedback", json=body)

    assert first.status_code == 200
    assert duplicate.status_code == 429
    assert duplicate.json()["detail"] == "INSIGHT_FEEDBACK_RATE_LIMITED"

def test_submit_feedback_requires_current_authenticated_user(insights_client):
    from api.auth import get_current_user_id
    from api.main import app

    app.dependency_overrides.pop(get_current_user_id)
    response = insights_client.post(
        "/api/insights/daily_brief/feedback",
        json={"vote": "up", "dataset_hash": DATASET_HASH},
    )
    assert response.status_code == 401
