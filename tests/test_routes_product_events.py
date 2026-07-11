"""Tests for the authenticated product-event ingestion endpoint."""
from __future__ import annotations

import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def product_events_client(monkeypatch):
    """TestClient with a current-user override and fresh in-memory guards."""
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

    user_id = "test-user-product-events"
    db = db_session.SessionLocal()
    try:
        from db.models import User, UserConfig

        db.add(User(
            id=user_id,
            email="product-events@example.com",
            hashed_password="test",
            is_active=True,
        ))
        db.add(UserConfig(user_id=user_id))
        db.commit()
    finally:
        db.close()

    from api.auth import get_current_user_id
    from api.auth_rate_limit import _SlidingWindow
    from api.main import app
    from api.routes import product_events

    app.dependency_overrides[get_current_user_id] = lambda: user_id
    product_events._EVENT_RATE_LIMIT = _SlidingWindow(60, 60, 10_000)
    product_events._EVENT_DEDUP = _SlidingWindow(1, 5, 50_000)

    yield TestClient(app)

    app.dependency_overrides.clear()
    tmpdir.cleanup()


def test_product_event_emits_once_and_deduplicates(
    product_events_client, monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        "api.routes.product_events.telemetry.record_product_event",
        lambda **kwargs: calls.append(kwargs),
    )
    body = {
        "event_name": "today_brief_rendered",
        "surface": "web",
        "app_version": "2026.07.1",
    }

    first = product_events_client.post("/api/product-events", json=body)
    second = product_events_client.post("/api/product-events", json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == {"accepted": True, "duplicate": False}
    assert second.json() == {"accepted": True, "duplicate": True}
    assert calls == [{
        "event_name": "today_brief_rendered",
        "surface": "web",
        "app_version": "2026.07.1",
        "response": None,
        "user_id": "test-user-product-events",
    }]


def test_product_event_requires_and_restricts_decision_response(product_events_client):
    missing = product_events_client.post(
        "/api/product-events",
        json={
            "event_name": "today_feedback_submitted",
            "surface": "miniapp",
            "app_version": "develop",
        },
    )
    assert missing.status_code == 422

    extra = product_events_client.post(
        "/api/product-events",
        json={
            "event_name": "app_opened",
            "surface": "web",
            "app_version": "develop",
            "response": "confirmed_plan",
        },
    )
    assert extra.status_code == 422

    invalid = product_events_client.post(
        "/api/product-events",
        json={
            "event_name": "today_feedback_submitted",
            "surface": "web",
            "app_version": "develop",
            "response": "other",
        },
    )
    assert invalid.status_code == 422

    unknown_event = product_events_client.post(
        "/api/product-events",
        json={
            "event_name": "health_score_viewed",
            "surface": "web",
            "app_version": "develop",
        },
    )
    assert unknown_event.status_code == 422

    oversized_version = product_events_client.post(
        "/api/product-events",
        json={
            "event_name": "app_opened",
            "surface": "web",
            "app_version": "x" * 65,
        },
    )
    assert oversized_version.status_code == 422
    sensitive_version = product_events_client.post(
        "/api/product-events",
        json={
            "event_name": "app_opened",
            "surface": "web",
            "app_version": "user@example.com",
        },
    )
    assert sensitive_version.status_code == 422
    secret_like_version = product_events_client.post(
        "/api/product-events",
        json={
            "event_name": "app_opened",
            "surface": "web",
            "app_version": "sk-abcdefghijklmnopqrstuvwxyz123456",
        },
    )
    assert secret_like_version.status_code == 422
    numeric_secret_version = product_events_client.post(
        "/api/product-events",
        json={
            "event_name": "app_opened",
            "surface": "web",
            "app_version": "2026.07.4111111111111111",
        },
    )
    assert numeric_secret_version.status_code == 422

    ci_build_version = product_events_client.post(
        "/api/product-events",
        json={
            "event_name": "app_opened",
            "surface": "miniapp",
            "app_version": "2026.07.04.1234-abc1234",
        },
    )
    assert ci_build_version.status_code == 200


def test_product_event_accepts_one_response_for_a_rendered_prompt(
    product_events_client, monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        "api.routes.product_events.telemetry.record_product_event",
        lambda **kwargs: calls.append(kwargs),
    )
    claim = product_events_client.post(
        "/api/product-events/today-feedback-claim",
    )
    body = {
        "event_name": "today_feedback_submitted",
        "surface": "miniapp",
        "app_version": " develop ",
        "response": "confirmed_plan",
    }
    response = product_events_client.post("/api/product-events", json=body)
    second_vote = product_events_client.post(
        "/api/product-events",
        json={**body, "response": "changed_plan"},
    )

    assert claim.json() == {"accepted": True, "duplicate": False}
    assert response.status_code == 200
    assert response.json() == {"accepted": True, "duplicate": False}
    assert second_vote.json() == {"accepted": True, "duplicate": True}
    assert calls == [
        {
            "event_name": "today_feedback_shown",
            "surface": "miniapp",
            "app_version": "develop",
            "response": None,
            "user_id": "test-user-product-events",
        },
        {
            "event_name": "today_feedback_submitted",
            "surface": "miniapp",
            "app_version": "develop",
            "response": "confirmed_plan",
            "user_id": "test-user-product-events",
        },
    ]


def test_today_feedback_claim_is_shared_and_confirmed_after_render(
    product_events_client, monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        "api.routes.product_events.telemetry.record_product_event",
        lambda **kwargs: calls.append(kwargs),
    )
    claim_url = "/api/product-events/today-feedback-claim"
    web = {
        "event_name": "today_feedback_shown",
        "surface": "web",
        "app_version": "2026.07.1",
    }
    miniapp = {
        "event_name": "today_feedback_shown",
        "surface": "miniapp",
        "app_version": "2026.07.1",
    }

    first_claim = product_events_client.post(claim_url)
    competing_claim = product_events_client.post(claim_url)
    shown = product_events_client.post("/api/product-events", json=web)
    repeated_confirmation = product_events_client.post(
        "/api/product-events",
        json=miniapp,
    )

    assert first_claim.json() == {"accepted": True, "duplicate": False}
    assert competing_claim.json() == {"accepted": True, "duplicate": True}
    assert shown.json() == {"accepted": True, "duplicate": False}
    assert repeated_confirmation.json() == {"accepted": True, "duplicate": True}
    assert [call["surface"] for call in calls] == ["web"]

    from db import session as db_session
    from db.models import UserConfig

    db = db_session.SessionLocal()
    try:
        row = db.query(UserConfig).filter(
            UserConfig.user_id == "test-user-product-events",
        ).one()
        row.today_decision_check_shown_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=8)
        )
        row.today_decision_check_claimed_at = None
        db.commit()
    finally:
        db.close()

    next_claim = product_events_client.post(claim_url)
    shown_after_cadence = product_events_client.post(
        "/api/product-events",
        json=miniapp,
    )
    assert next_claim.json() == {"accepted": True, "duplicate": False}
    assert shown_after_cadence.json() == {"accepted": True, "duplicate": False}
    assert [call["surface"] for call in calls] == ["web", "miniapp"]


def test_concurrent_today_feedback_claims_serialize_on_sqlite(
    product_events_client,
):
    claim_url = "/api/product-events/today-feedback-claim"
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(
            lambda _: product_events_client.post(claim_url),
            range(2),
        ))

    assert [response.status_code for response in responses] == [200, 200]
    duplicates = sorted(response.json()["duplicate"] for response in responses)
    assert duplicates == [False, True]


def test_today_feedback_claim_expires_without_counting_as_shown(
    product_events_client,
):
    claim_url = "/api/product-events/today-feedback-claim"
    first_claim = product_events_client.post(claim_url)
    assert first_claim.json() == {"accepted": True, "duplicate": False}

    from db import session as db_session
    from db.models import UserConfig

    db = db_session.SessionLocal()
    try:
        row = db.query(UserConfig).filter(
            UserConfig.user_id == "test-user-product-events",
        ).one()
        row.today_decision_check_claimed_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=3)
        )
        db.commit()
    finally:
        db.close()

    retried_claim = product_events_client.post(claim_url)
    assert retried_claim.json() == {"accepted": True, "duplicate": False}


def test_today_feedback_submission_survives_expired_claim_lease(
    product_events_client, monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        "api.routes.product_events.telemetry.record_product_event",
        lambda **kwargs: calls.append(kwargs),
    )
    claim_url = "/api/product-events/today-feedback-claim"
    first_claim = product_events_client.post(claim_url)
    assert first_claim.json() == {"accepted": True, "duplicate": False}

    from db import session as db_session
    from db.models import UserConfig

    db = db_session.SessionLocal()
    try:
        row = db.query(UserConfig).filter(
            UserConfig.user_id == "test-user-product-events",
        ).one()
        row.today_decision_check_claimed_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=3)
        )
        db.commit()
    finally:
        db.close()

    submitted = product_events_client.post(
        "/api/product-events",
        json={
            "event_name": "today_feedback_submitted",
            "surface": "web",
            "app_version": "develop",
            "response": "confirmed_plan",
        },
    )
    assert submitted.status_code == 200
    assert submitted.json() == {"accepted": True, "duplicate": False}
    assert [call["event_name"] for call in calls] == [
        "today_feedback_shown",
        "today_feedback_submitted",
    ]


def test_today_feedback_submission_accepts_prompt_within_cadence(
    product_events_client,
):
    claim_url = "/api/product-events/today-feedback-claim"
    claim = product_events_client.post(claim_url)
    assert claim.json() == {"accepted": True, "duplicate": False}
    shown = product_events_client.post(
        "/api/product-events",
        json={
            "event_name": "today_feedback_shown",
            "surface": "miniapp",
            "app_version": "develop",
        },
    )
    assert shown.json() == {"accepted": True, "duplicate": False}

    from db import session as db_session
    from db.models import UserConfig

    db = db_session.SessionLocal()
    try:
        row = db.query(UserConfig).filter(
            UserConfig.user_id == "test-user-product-events",
        ).one()
        row.today_decision_check_shown_at = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3)
        )
        db.commit()
    finally:
        db.close()

    submitted = product_events_client.post(
        "/api/product-events",
        json={
            "event_name": "today_feedback_submitted",
            "surface": "miniapp",
            "app_version": "develop",
            "response": "changed_plan",
        },
    )
    assert submitted.status_code == 200
    assert submitted.json() == {"accepted": True, "duplicate": False}


def test_today_feedback_shown_requires_a_recent_claim(
    product_events_client, monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        "api.routes.product_events.telemetry.record_product_event",
        lambda **kwargs: calls.append(kwargs),
    )
    response = product_events_client.post(
        "/api/product-events",
        json={
            "event_name": "today_feedback_shown",
            "surface": "web",
            "app_version": "develop",
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "PRODUCT_EVENT_PROMPT_NOT_CLAIMED"
    assert calls == []

    submission = product_events_client.post(
        "/api/product-events",
        json={
            "event_name": "today_feedback_submitted",
            "surface": "web",
            "app_version": "develop",
            "response": "not_helpful",
        },
    )
    assert submission.status_code == 409
    assert submission.json()["detail"] == "PRODUCT_EVENT_PROMPT_NOT_RENDERED"


def test_today_feedback_claim_rejects_inactive_account(product_events_client):
    from db import session as db_session
    from db.models import User, UserConfig

    db = db_session.SessionLocal()
    try:
        user = db.query(User).filter(User.id == "test-user-product-events").one()
        user.is_active = False
        db.commit()
    finally:
        db.close()

    response = product_events_client.post(
        "/api/product-events/today-feedback-claim",
    )
    assert response.status_code == 401

    db = db_session.SessionLocal()
    try:
        config = db.query(UserConfig).filter(
            UserConfig.user_id == "test-user-product-events",
        ).one()
        assert config.today_decision_check_claimed_at is None
        assert config.today_decision_check_shown_at is None
        assert config.today_decision_check_submitted_at is None
    finally:
        db.close()


def test_today_feedback_lock_refreshes_preloaded_inactive_user(
    product_events_client,
):
    from fastapi import HTTPException

    from api.routes import product_events
    from db import session as db_session
    from db.models import User

    stale_db = db_session.SessionLocal()
    fresh_db = db_session.SessionLocal()
    try:
        stale_db.query(User).filter(User.id == "test-user-product-events").one()
        user = fresh_db.query(User).filter(
            User.id == "test-user-product-events",
        ).one()
        user.is_active = False
        fresh_db.commit()

        with pytest.raises(HTTPException) as exc:
            product_events._locked_user_config(
                stale_db,
                "test-user-product-events",
                create=True,
            )
        assert exc.value.status_code == 401
        assert exc.value.detail == "UNAUTHORIZED"
    finally:
        stale_db.close()
        fresh_db.close()


def test_product_event_rejects_unknown_fields(product_events_client):
    response = product_events_client.post(
        "/api/product-events",
        json={
            "event_name": "app_opened",
            "surface": "web",
            "app_version": "develop",
            "health_value": 42,
        },
    )
    assert response.status_code == 422


def test_product_event_rate_limits_distinct_events(product_events_client, monkeypatch):
    from api.auth_rate_limit import _SlidingWindow
    from api.routes import product_events

    product_events._EVENT_RATE_LIMIT = _SlidingWindow(1, 60, 10_000)
    monkeypatch.setattr(
        "api.routes.product_events.telemetry.record_product_event",
        lambda **kwargs: None,
    )

    first = product_events_client.post(
        "/api/product-events",
        json={"event_name": "app_opened", "surface": "web", "app_version": "develop"},
    )
    second = product_events_client.post(
        "/api/product-events",
        json={
            "event_name": "today_brief_rendered",
            "surface": "web",
            "app_version": "develop",
        },
    )
    retry = product_events_client.post(
        "/api/product-events",
        json={
            "event_name": "today_brief_rendered",
            "surface": "web",
            "app_version": "develop",
        },
    )
    assert first.status_code == 200
    assert second.status_code == 429
    assert retry.status_code == 429
    assert second.json()["detail"] == "PRODUCT_EVENT_RATE_LIMITED"
    assert int(second.headers["Retry-After"]) >= 1


def test_product_event_requires_authentication(product_events_client):
    from api.auth import get_current_user_id
    from api.main import app

    app.dependency_overrides.pop(get_current_user_id)
    response = product_events_client.post(
        "/api/product-events",
        json={"event_name": "app_opened", "surface": "web", "app_version": "develop"},
    )
    claim = product_events_client.post("/api/product-events/today-feedback-claim")
    assert response.status_code == 401
    assert claim.status_code == 401
