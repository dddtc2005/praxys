"""Integration tests for the admin operations summary contract."""
from __future__ import annotations

import importlib
import tempfile
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient


def _build(monkeypatch, data_dir: str):
    monkeypatch.setenv("DATA_DIR", data_dir)
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "false")
    monkeypatch.setenv(
        "PRAXYS_LOCAL_ENCRYPTION_KEY",
        "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=",
    )
    monkeypatch.setenv("PRAXYS_AUTH_RATE_LIMIT_DISABLED", "true")
    monkeypatch.delenv("PRAXYS_ADMIN_EMAIL", raising=False)

    from db import session as db_session

    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    import api.app_config
    import api.invitations
    import api.users

    importlib.reload(api.invitations)
    importlib.reload(api.app_config)
    importlib.reload(api.users)

    import api.main

    importlib.reload(api.main)
    return api.main, db_session


@pytest.fixture
def env(monkeypatch):
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    db_session = None
    try:
        main, db_session = _build(monkeypatch, tmp.name)
        with TestClient(main.app) as client:
            yield client, db_session
    finally:
        if db_session is not None:
            try:
                if db_session.engine is not None:
                    db_session.engine.dispose()
            except Exception:
                pass
        tmp.cleanup()


def _register(client, email: str, invitation_code: str = ""):
    return client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "pw123456",
            "accepted_terms": True,
            "invitation_code": invitation_code,
        },
    )


def _login(client, email: str) -> str:
    response = client.post(
        "/api/auth/login",
        data={"username": email, "password": "pw123456"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


def _admin_headers(client) -> dict[str, str]:
    response = _register(client, "admin@praxys.run")
    assert response.status_code == 200
    return {"Authorization": f"Bearer {_login(client, 'admin@praxys.run')}"}


def _collect_keys(value) -> set[str]:
    if isinstance(value, dict):
        keys = set(value)
        for child in value.values():
            keys.update(_collect_keys(child))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for child in value:
            keys.update(_collect_keys(child))
        return keys
    return set()


def _trusted_azure_snapshots():
    from api.admin_azure_monitor import AzureSectionSnapshot

    as_of = datetime.now(timezone.utc)
    return {
        "alerts": AzureSectionSnapshot(
            freshness="fresh",
            as_of=as_of,
            reason=None,
            data={
                "total": 2,
                "firing": 1,
                "resolved": 1,
                "severity": {"sev0": 0, "sev1": 0, "sev2": 2, "sev3": 0, "sev4": 0},
                "states": {"new": 1, "acknowledged": 0, "closed": 1},
                "rules": [
                    {
                        "rule": "praxys-sync-systemic-failures",
                        "severity": "Sev2",
                        "firing": 1,
                        "resolved": 1,
                        "last_changed_at": "2026-07-19T01:01:00Z",
                    }
                ],
            },
        ),
        "service": AzureSectionSnapshot(
            freshness="fresh",
            as_of=as_of,
            reason=None,
            data={
                "requests": 100,
                "failed_requests": 4,
                "server_errors": 2,
                "failed_request_rate": 0.04,
                "server_error_rate": 0.02,
                "p95_request_ms": 480.0,
                "availability_checks": 24,
                "failed_availability_checks": 1,
                "availability_rate": 23 / 24,
                "p95_availability_ms": 210.0,
                "database_health_failures": 0,
            },
        ),
        "product": AzureSectionSnapshot(
            freshness="fresh",
            as_of=as_of,
            reason=None,
            data={
                "surfaces": [
                    {
                        "surface": "web",
                        "app_users": 10,
                        "today_users": 8,
                        "today_reach_rate": 0.8,
                        "decision_prompts": 6,
                        "decision_responses": 4,
                        "decision_response_rate": 2 / 3,
                        "reported_value_rate": 0.75,
                        "repeated_users": 5,
                        "repeated_rate": 0.625,
                    }
                ],
                "coach": [
                    {
                        "insight_type": "daily_brief",
                        "useful_votes": 7,
                        "total_votes": 9,
                        "useful_rate": 7 / 9,
                    }
                ],
            },
        ),
        "platform": AzureSectionSnapshot(
            freshness="fresh",
            as_of=as_of,
            reason=None,
            data={
                "systemic_affected_users": 3,
                "sync": [
                    {
                        "platform": "garmin",
                        "attempts": 20,
                        "successes": 17,
                        "failures": 3,
                        "failure_rate": 0.15,
                    }
                ],
                "systemic_failures": [
                    {
                        "platform": "garmin",
                        "failure_class": "token_rejected",
                        "failures": 3,
                        "affected_users": 3,
                    }
                ],
                "connections": [
                    {
                        "platform": "garmin",
                        "flow": "mfa",
                        "stage": "mfa_verify",
                        "outcome": "connected",
                        "attempts": 4,
                    }
                ],
            },
        ),
    }


def test_ops_summary_admin_only_window_validation_and_no_store(env):
    client, _ = env
    assert client.get("/api/admin/ops/summary").status_code == 401

    admin_headers = _admin_headers(client)
    response = client.get("/api/admin/ops/summary?window=28d", headers=admin_headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json()["window"] == "28d"
    assert client.get(
        "/api/admin/ops/summary?window=30d", headers=admin_headers
    ).status_code == 422

    code = client.post("/api/admin/invitations", headers=admin_headers, json={}).json()["code"]
    assert _register(client, "runner@praxys.run", invitation_code=code).status_code == 200
    normal_headers = {"Authorization": f"Bearer {_login(client, 'runner@praxys.run')}"}
    assert client.get("/api/admin/ops/summary", headers=normal_headers).status_code == 403


def test_ops_summary_aggregates_attention_without_pii(env, monkeypatch):
    client, db_session = env
    admin_headers = _admin_headers(client)

    import api.admin_ops as admin_ops

    monkeypatch.setattr(
        admin_ops,
        "get_ops_telemetry",
        lambda window: _trusted_azure_snapshots(),
    )
    monkeypatch.setattr(
        admin_ops,
        "azure_portal_links",
        lambda: ("https://portal.azure.com/alerts", "https://portal.azure.com/logs"),
    )

    from db.models import Feedback, ServiceIncident, User

    db = db_session.SessionLocal()
    admin = db.query(User).filter(User.email == "admin@praxys.run").one()
    db.add_all(
        [
            Feedback(
                user_id=admin.id,
                kind="bug",
                message="private critical feedback text",
                status="needs_review",
                priority="critical",
            ),
            Feedback(
                user_id=admin.id,
                kind="bug",
                message="private failed feedback text",
                status="failed",
                priority="high",
            ),
            Feedback(
                user_id=admin.id,
                kind="feature",
                message="private new feedback text",
                status="new",
            ),
            ServiceIncident(
                title="Elevated API latency",
                status="investigating",
                impact="critical",
                started_at=datetime.utcnow(),
            ),
        ]
    )
    db.commit()
    admin_id = admin.id
    db.close()

    response = client.get("/api/admin/ops/summary?window=7d", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "generated_at",
        "window",
        "attention",
        "service_health",
        "product_value",
        "service_telemetry",
        "product_telemetry",
        "azure_alerts",
        "platform_health",
        "links",
    }

    attention = body["attention"]
    assert attention["source"] == "praxys_database"
    assert attention["window"] == "live"
    assert attention["freshness"] == "fresh"
    assert attention["as_of"]
    assert attention["data"]["incident_counts"] == {
        "total": 1,
        "minor": 0,
        "major": 0,
        "critical": 1,
    }
    assert attention["data"]["active_incidents"][0]["title"] == "Elevated API latency"
    assert attention["data"]["feedback"] == {
        "needs_review": 1,
        "failed": 1,
        "new": 1,
        "actionable": 2,
        "critical": 1,
        "high": 1,
        "total": 3,
    }

    assert body["service_health"]["freshness"] == "fresh"
    assert {c["key"] for c in body["service_health"]["data"]["components"]} == {
        "api",
        "database",
        "sync",
    }
    assert body["product_value"]["data"]["registered_users"] == 1
    assert body["product_value"]["data"]["directional"] is True
    assert body["service_telemetry"]["data"]["server_error_rate"] == 0.02
    assert body["product_telemetry"]["data"]["surfaces"][0]["today_reach_rate"] == 0.8
    assert body["product_telemetry"]["window"] == "28d"
    assert body["product_telemetry"]["data"]["coach"][0]["useful_votes"] == 7
    assert body["azure_alerts"]["freshness"] == "fresh"
    assert body["azure_alerts"]["window"] == "7d"
    assert body["azure_alerts"]["data"]["firing"] == 1
    assert body["platform_health"]["freshness"] == "fresh"
    assert body["platform_health"]["data"]["systemic_affected_users"] == 3
    assert body["platform_health"]["data"]["systemic_failures"][0] == {
        "platform": "garmin",
        "failure_class": "token_rejected",
        "failures": 3,
        "affected_users": 3,
    }
    assert body["links"]["azure_alerts"] == "https://portal.azure.com/alerts"
    assert body["links"]["azure_logs"] == "https://portal.azure.com/logs"
    assert body["links"]["telemetry_trust_issue"].endswith("/issues/417")

    forbidden_keys = {
        "email",
        "user_id",
        "user_id_hash",
        "message",
        "comment",
        "comment_excerpt",
        "invitation_code",
        "screenshot",
        "image_description",
    }
    assert not (forbidden_keys & _collect_keys(body))
    serialized = response.text
    assert "admin@praxys.run" not in serialized
    assert admin_id not in serialized
    assert "private critical feedback text" not in serialized


def test_ops_summary_partial_failure_isolated(env, monkeypatch):
    client, _ = env
    admin_headers = _admin_headers(client)

    import api.admin_ops as admin_ops

    def fail_attention(_db):
        raise RuntimeError("synthetic aggregate failure")

    monkeypatch.setattr(admin_ops, "_attention_data", fail_attention)
    response = client.get("/api/admin/ops/summary", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["attention"]["freshness"] == "unavailable"
    assert body["attention"]["data"] is None
    assert body["attention"]["reason"] == "section_refresh_failed"
    assert body["service_health"]["freshness"] == "fresh"
    assert body["product_value"]["freshness"] == "fresh"
    assert body["service_telemetry"]["freshness"] == "unavailable"
    assert (
        body["service_telemetry"]["reason"]
        == "azure_telemetry_not_configured"
    )
