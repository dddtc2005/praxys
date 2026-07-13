"""Tests for the in-app feedback feature.

Covers the deterministic PII scrub, the submit endpoint (persist + schedule +
rate-limit), the background triage pipeline (scrub-before-publish + the
no-GitHub "triaged" terminal state), and the admin list / retry / reject
actions. Route functions are called directly (passing user_id + db) — the same
dependency-bypass pattern as tests/test_announcements.py.
"""
from __future__ import annotations

import base64
import tempfile

import pytest
from fastapi import BackgroundTasks, HTTPException


# ---------------------------------------------------------------------------
# Pure scrub unit tests (no DB)
# ---------------------------------------------------------------------------


def test_scrub_text_redacts_pii_but_keeps_training_numbers():
    from api.feedback_scrub import scrub_text

    raw = (
        "Contact jane.doe@example.com or call 13800138000. "
        "Bearer token=ghp_abcdefghijklmnopqrstuvwx12345 from 192.168.1.42, "
        "log at C:\\Users\\jane\\AppData. My avg power was 285 and HR 165."
    )
    out = scrub_text(raw)
    assert "jane.doe@example.com" not in out
    assert "ghp_abcdefghijklmnopqrstuvwx12345" not in out
    assert "192.168.1.42" not in out
    assert "13800138000" not in out
    assert "\\Users\\jane" not in out
    # Training-relevant short numbers must survive.
    assert "285" in out
    assert "165" in out


def test_scrub_redacts_modern_api_keys():
    """Modern hyphenated keys (OpenAI sk-proj-/sk-svcacct-, GitHub fine-grained
    PAT) must be redacted whole — a regression guard for the older pattern that
    stopped at the first hyphen and leaked sk-proj- keys."""
    from api.feedback_scrub import scrub_text

    secrets = [
        "sk-proj-abcdEFGH1234567890ijklMNOP_qrst-uvwx",
        "sk-svcacct-AbC0123456789defGHIjklMNopQR",
        "github_pat_11ABCDEFG0aBcDeFgHiJ_KLmnopQRstuvWXyz123",
        "sk-ABCDEFGHIJKLMNOPqrstuvwx0123456789",
    ]
    for secret in secrets:
        out = scrub_text(f"my key is {secret} thanks")
        assert secret not in out, f"leaked: {secret}"
        assert "[redacted-key]" in out
    # A normal hyphenated phrase that merely starts with "sk-" must survive.
    assert "sk-based" in scrub_text("we use sk-based zones")


def test_scrub_redacts_formatted_phone_and_account_numbers():
    from api.feedback_scrub import scrub_text

    raw = (
        "Call 138-0013-8000 or (555) 123-4567. "
        "Card 4111 1111 1111 1111. Training date 2026-07-12, power 285."
    )
    out = scrub_text(raw)

    assert "138-0013-8000" not in out
    assert "(555) 123-4567" not in out
    assert "4111 1111 1111 1111" not in out
    assert out.count("[redacted-number]") == 3
    assert "2026-07-12" in out
    assert "285" in out


def test_scrub_redacts_credential_labels_with_common_phrasing():
    from api.feedback_scrub import scrub_text

    secrets = ("hunter2", "abc123", "token-value", "quoted secret")
    raw = (
        "my password is hunter2; API key: abc123; "
        "Authorization: Bearer token-value; secret = 'quoted secret'"
    )
    out = scrub_text(raw)

    for secret in secrets:
        assert secret not in out
    assert out.count("[redacted]") == 4

def test_scrub_redacts_quoted_json_credentials_without_corrupting_json():
    import json

    from api.feedback_scrub import scrub_text

    raw = json.dumps({
        "password": "hunter2",
        "access_token": "oauthCredential987654321",
        "nested": {"client_secret": "clientCredential987654321"},
        "power": 285,
    })
    out = scrub_text(raw)
    parsed = json.loads(out)

    assert parsed["password"] == "[redacted]"
    assert parsed["access_token"] == "[redacted]"
    assert parsed["nested"]["client_secret"] == "[redacted]"
    assert parsed["power"] == 285


def test_scrub_redacts_nested_json_credentials_without_leaking_array_values():
    import json

    from api.feedback_scrub import scrub_text

    raw = json.dumps({
        "tokens": ["firstsecret", "secondsecret"],
        "nested": {
            "OPENAI_API_KEY": {"primary": "thirdsecret"},
            "connectionString": {"primary": "fourthsecret"},
            "proxy_authorization": "fifthsecret",
            "headers": [
                {"Name": "Proxy-Authorization", "Value": "sixthsecret"},
            ],
            "note": "Contact jane@example.com after a 250 W workout",
        },
        "phone": 15551234567,
        "ok": 1,
    })

    out = scrub_text(raw)
    parsed = json.loads(out)

    assert parsed["tokens"] == "[redacted]"
    assert parsed["nested"]["OPENAI_API_KEY"] == "[redacted]"
    assert parsed["nested"]["connectionString"] == "[redacted]"
    assert parsed["nested"]["proxy_authorization"] == "[redacted]"
    assert parsed["nested"]["headers"][0]["Value"] == "[redacted]"
    assert parsed["nested"]["note"] == (
        "Contact [redacted-email] after a 250 W workout"
    )
    assert parsed["phone"] == "[redacted-number]"
    assert parsed["ok"] == 1
    for secret in (
        "firstsecret", "secondsecret", "thirdsecret", "fourthsecret",
        "fifthsecret", "sixthsecret",
    ):
        assert secret not in out


def test_scrub_redacts_compound_oauth_credential_labels():
    from api.feedback_scrub import scrub_text

    credentials = {
        "access_token": "ZXhhbXBsZU9BdXRoVmFsdWU987654",
        "refresh-token": "refreshCredential987654321",
        "client_secret": "clientCredential987654321",
    }
    raw = "; ".join(f"{label}={value}" for label, value in credentials.items())
    out = scrub_text(raw)

    for value in credentials.values():
        assert value not in out
    assert out.count("[redacted]") == 3

def test_scrub_redacts_complete_authorization_header_value():
    from api.feedback_scrub import scrub_text

    credential = "dXNlcjpwYXNzd29yZA=="
    out = scrub_text(f"Authorization: Basic {credential}\nrequest failed")

    assert credential not in out
    assert "Authorization [redacted]" in out
    assert "request failed" in out


def test_scrub_redacts_connection_credentials_cookies_and_private_keys():
    from api.feedback_scrub import scrub_text

    secrets = {
        "aws": "aws-secret-value-123",
        "account": "azure-storage-account-key-456",
        "database": "database-credential-value-789",
        "cookie": "session=private-cookie-value",
        "private_key": "private-key-material",
        "servicebus": "servicebus-shared-key-890",
        "uri_password": "uri-password-value-321",
        "lowercase_key": "lowercase-private-key-654",
    }
    raw = (
        f"AWS_SECRET_ACCESS_KEY={secrets['aws']}\n"
        f"DefaultEndpointsProtocol=https;AccountKey={secrets['account']};EndpointSuffix=core.windows.net\n"
        f"DATABASE_URL={secrets['database']}\n"
        f"PRAXYS_DATABASE_URL=postgresql://runner:{secrets['uri_password']}@db.example.test/praxys\n"
        f"AZURE_SERVICEBUS_CONNECTION_STRING=Endpoint=sb://bus.example.test;"
        f"SharedAccessKeyName=Root;SharedAccessKey={secrets['servicebus']}\n"
        f"Connection failed for postgresql://runner:{secrets['uri_password']}@db.example.test/praxys\n"
        f"aws_secret_access_key={secrets['lowercase_key']}\n"
        f"Cookie: {secrets['cookie']}\n"
        "-----BEGIN PRIVATE KEY-----\n"
        f"{secrets['private_key']}\n"
        "-----END PRIVATE KEY-----"
    )

    out = scrub_text(raw)

    for secret in secrets.values():
        assert secret not in out
    assert "AWS_SECRET_ACCESS_KEY=[redacted]" in out
    assert "AccountKey=[redacted]" in out
    assert "PRAXYS_DATABASE_URL=[redacted]" in out
    assert "SharedAccessKey=[redacted]" in out
    assert "aws_secret_access_key=[redacted]" in out
    assert "postgresql://[redacted]@db.example.test/praxys" in out
    assert "Cookie: [redacted]" in out
    assert "[redacted-private-key]" in out

def test_scrub_context_drops_unknown_keys_and_scrubs_values():
    from api.feedback_scrub import scrub_context

    cleaned = scrub_context(
        {
            "page": "/today",
            "app_version": "2026.06.1",
            "user_agent": "Mozilla contact me@x.com",
            "secret_field": "should-be-dropped",
        }
    )
    assert cleaned["page"] == "/today"
    assert cleaned["app_version"] == "2026.06.1"
    assert "me@x.com" not in cleaned["user_agent"]
    assert "secret_field" not in cleaned


def test_scrub_context_preserves_valid_ci_build_versions():
    from api.feedback_scrub import scrub_context

    valid = scrub_context({
        "app_version": "2026.07.04.1234-abc1234",
        "api_version": "2026.07.1",
    })
    assert valid == {
        "app_version": "2026.07.04.1234-abc1234",
        "api_version": "2026.07.1",
    }

    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    unsafe = scrub_context({
        "app_version": "2026.07.4111111111111111",
        "api_version": secret,
    })
    assert unsafe["app_version"] != "2026.07.4111111111111111"
    assert secret not in unsafe["api_version"]


def test_scrub_text_preserves_valid_ci_build_version():
    from api.feedback_scrub import scrub_text

    build_version = "2026.07.13.12345678-deadbee"
    secret = "sk-abcdefghijklmnopqrstuvwxyz123456"
    cleaned = scrub_text(f"app_version={build_version}\napi_key={secret}")

    assert build_version in cleaned
    assert secret not in cleaned


def test_scrub_text_redacts_invalid_build_like_long_value():
    from api.feedback_scrub import scrub_text

    invalid_value = "2026.07.13.12345678-deadbeeX"
    cleaned = scrub_text(f"app_version={invalid_value}")

    assert invalid_value not in cleaned
    assert "[redacted-number]" in cleaned


# ---------------------------------------------------------------------------
# DB-backed fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def db_with_users(monkeypatch):
    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    monkeypatch.setenv("DATA_DIR", tmpdir.name)
    monkeypatch.setenv("PRAXYS_LOCAL_ENCRYPTION_KEY", "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=")
    # Triage must run in its fully-unconfigured mode: no LLM, no GitHub.
    monkeypatch.delenv("AZURE_AI_ENDPOINT", raising=False)
    monkeypatch.delenv("PRAXYS_GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("PRAXYS_GITHUB_APP_INSTALLATION_ID", raising=False)
    monkeypatch.delenv("PRAXYS_GITHUB_APP_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("PRAXYS_FEEDBACK_GITHUB_REPO", raising=False)
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)

    from db import session as db_session

    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    # get_client is process-memoised — clear so a prior test that set an
    # endpoint can't leak an enabled client into this unconfigured run.
    from api import llm

    llm.get_client.cache_clear()

    from db.models import User

    db = db_session.SessionLocal()
    admin_id, user_id = "admin-fb", "user-fb"
    db.add(User(id=admin_id, email="admin@fb.test", hashed_password="x", is_superuser=True))
    db.add(User(id=user_id, email="user@fb.test", hashed_password="x", is_superuser=False))
    db.commit()
    try:
        yield db, db_session, admin_id, user_id
    finally:
        db.close()
        if db_session.engine is not None:
            db_session.engine.dispose()
        db_session.engine = None
        db_session.SessionLocal = None
        db_session.async_engine = None
        db_session.AsyncSessionLocal = None
        tmpdir.cleanup()


# ---------------------------------------------------------------------------
# Submit endpoint
# ---------------------------------------------------------------------------


def test_submit_stores_row_and_schedules_triage(db_with_users):
    from api.routes.feedback import submit_feedback, FeedbackRequest
    from db.models import Feedback

    db, _, _, user_id = db_with_users
    bg = BackgroundTasks()
    resp = submit_feedback(
        FeedbackRequest(kind="bug", message="Charts fail to load", context={"page": "/training"}),
        background_tasks=bg,
        user_id=user_id,
        db=db,
    )
    assert resp["ok"] is True
    assert resp["status"] == "received"
    assert len(bg.tasks) == 1  # triage scheduled

    row = db.query(Feedback).filter(Feedback.id == resp["id"]).first()
    assert row.status == "new"
    assert row.kind == "bug"
    assert row.user_id == user_id


def test_submit_rate_limited(db_with_users):
    from api.routes.feedback import submit_feedback, FeedbackRequest, _MAX_PER_WINDOW

    db, _, _, user_id = db_with_users
    for _ in range(_MAX_PER_WINDOW):
        submit_feedback(
            FeedbackRequest(kind="other", message="x"),
            background_tasks=BackgroundTasks(),
            user_id=user_id,
            db=db,
        )
    with pytest.raises(HTTPException) as exc:
        submit_feedback(
            FeedbackRequest(kind="other", message="one too many"),
            background_tasks=BackgroundTasks(),
            user_id=user_id,
            db=db,
        )
    assert exc.value.status_code == 429


# ---------------------------------------------------------------------------
# Background triage
# ---------------------------------------------------------------------------


def test_triage_without_github_marks_triaged_and_scrubs(db_with_users):
    from api.feedback_triage import triage_and_publish
    from db.models import Feedback

    db, _, _, user_id = db_with_users
    row = Feedback(
        user_id=user_id,
        kind="bug",
        message="App crashed, email me at runner@example.com",
        status="new",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "triaged"  # no GitHub configured
    assert result["used_llm"] is False  # no Azure endpoint

    db.refresh(row)
    assert row.status == "triaged"
    assert row.ai_title
    assert row.ai_body
    # The scrubbed body that would be published must not leak the raw email.
    assert "runner@example.com" not in row.ai_body
    assert "[redacted-email]" in row.ai_body
    assert "bug" in (row.ai_labels or [])
    assert "feedback" in (row.ai_labels or [])


def test_triage_is_idempotent_on_published_row(db_with_users):
    from api.feedback_triage import triage_and_publish
    from db.models import Feedback

    db, _, _, user_id = db_with_users
    row = Feedback(user_id=user_id, kind="other", message="done", status="issue_created")
    db.add(row)
    db.commit()
    db.refresh(row)

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "skipped"


# ---------------------------------------------------------------------------
# Sensitivity gate (same public repo + AI gate)
# ---------------------------------------------------------------------------


def _stub_github(monkeypatch, calls):
    from api import feedback_triage as ft

    monkeypatch.setattr(ft.github_issues, "is_configured", lambda: True)

    def _create(**kwargs):
        calls.append(kwargs)
        return {"number": 101, "url": "https://github.com/x/y/issues/101"}

    monkeypatch.setattr(ft.github_issues, "create_issue", _create)


def _stub_llm(monkeypatch, *, sensitive, priority=None, kind="bug", agent_eligible=True):
    from api import feedback_triage as ft

    payload = {
        "kind": kind,
        "title": "Charts crash on Training",
        "body": "The training charts fail to render.",
        "contains_sensitive": sensitive,
        "agent_eligible": agent_eligible,
    }
    if priority is not None:
        payload["priority"] = priority
    monkeypatch.setattr(ft.llm, "get_client", lambda: object())
    monkeypatch.setattr(ft.llm, "chat_json", lambda *a, **k: payload)


def _new_row(db, user_id, message, kind="bug"):
    from db.models import Feedback

    row = Feedback(user_id=user_id, kind=kind, message=message, status="new")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_gate_holds_when_no_ai_and_public_repo(db_with_users, monkeypatch):
    """GitHub configured but no AI to judge sensitivity → park for admin."""
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    calls: list = []
    _stub_github(monkeypatch, calls)
    row = _new_row(db, user_id, "The goal page is confusing.")

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "needs_review"
    assert calls == []  # nothing published


def test_gate_autofiles_without_ai_when_opted_in(db_with_users, monkeypatch):
    """Operator opts into scrub-only auto-filing → clean report is published."""
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    monkeypatch.setenv("PRAXYS_FEEDBACK_AUTOFILE_WITHOUT_AI", "true")
    calls: list = []
    _stub_github(monkeypatch, calls)
    row = _new_row(db, user_id, "The goal page is confusing.")

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "issue_created"
    assert len(calls) == 1


def test_gate_holds_when_secret_present_even_if_opted_in(db_with_users, monkeypatch):
    """A scrubbed key/token always parks the row, overriding the opt-in."""
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    monkeypatch.setenv("PRAXYS_FEEDBACK_AUTOFILE_WITHOUT_AI", "true")
    calls: list = []
    _stub_github(monkeypatch, calls)
    row = _new_row(db, user_id, "My key sk-proj-abcdEFGH1234567890ijklMNOP_qrst leaked")

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "needs_review"
    assert calls == []


def test_gate_holds_when_llm_flags_sensitive(db_with_users, monkeypatch):
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    calls: list = []
    _stub_github(monkeypatch, calls)
    _stub_llm(monkeypatch, sensitive=True)
    row = _new_row(db, user_id, "Something about my health data")

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "needs_review"
    assert result["used_llm"] is True
    assert calls == []


def test_gate_publishes_when_llm_says_clean(db_with_users, monkeypatch):
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    calls: list = []
    _stub_github(monkeypatch, calls)
    _stub_llm(monkeypatch, sensitive=False)
    row = _new_row(db, user_id, "Charts fail to load on the training page")

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "issue_created"
    assert len(calls) == 1
    db.refresh(row)
    assert row.github_issue_number == 101


def test_admin_approve_publishes_parked_row(db_with_users, monkeypatch):
    from api.routes.feedback import update_feedback, FeedbackAction
    from api.feedback_triage import triage_and_publish

    db, _, admin_id, user_id = db_with_users
    calls: list = []
    _stub_github(monkeypatch, calls)
    row = _new_row(db, user_id, "Parked report awaiting review")

    # No AI → parked.
    triage_and_publish(row.id, _session=db)
    db.refresh(row)
    assert row.status == "needs_review"

    out = update_feedback(row.id, FeedbackAction(action="approve"), BackgroundTasks(), user_id=admin_id, db=db)
    assert out["status"] == "issue_created"
    assert out["github_issue_number"] == 101
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


def test_admin_list_requires_admin(db_with_users):
    from api.routes.feedback import list_feedback

    db, _, admin_id, user_id = db_with_users
    with pytest.raises(HTTPException) as exc:
        list_feedback(user_id=user_id, db=db)
    assert exc.value.status_code == 403

    # Admin can list.
    out = list_feedback(user_id=admin_id, db=db)
    assert isinstance(out, list)


def test_admin_reject_and_retry(db_with_users):
    from api.routes.feedback import submit_feedback, update_feedback, FeedbackRequest, FeedbackAction
    from db.models import Feedback

    db, _, admin_id, user_id = db_with_users
    submitted = submit_feedback(
        FeedbackRequest(kind="feature", message="add dark mode toggle"),
        background_tasks=BackgroundTasks(),
        user_id=user_id,
        db=db,
    )
    fid = submitted["id"]

    rejected = update_feedback(fid, FeedbackAction(action="reject"), BackgroundTasks(), user_id=admin_id, db=db)
    assert rejected["status"] == "rejected"

    bg = BackgroundTasks()
    retried = update_feedback(fid, FeedbackAction(action="retry"), bg, user_id=admin_id, db=db)
    assert retried["status"] == "new"
    assert len(bg.tasks) == 1

    # Retrying an already-published row (linked to a GitHub issue) is a conflict.
    row = db.query(Feedback).filter(Feedback.id == fid).first()
    row.status = "issue_created"
    row.github_issue_number = 101
    db.commit()
    with pytest.raises(HTTPException) as exc:
        update_feedback(fid, FeedbackAction(action="retry"), BackgroundTasks(), user_id=admin_id, db=db)
    assert exc.value.status_code == 409


def test_admin_action_on_missing_row_404(db_with_users):
    from api.routes.feedback import update_feedback, FeedbackAction

    db, _, admin_id, _ = db_with_users
    with pytest.raises(HTTPException) as exc:
        update_feedback(999999, FeedbackAction(action="reject"), BackgroundTasks(), user_id=admin_id, db=db)
    assert exc.value.status_code == 404


def test_admin_feedback_summary(db_with_users):
    """Summary counts power the admin sidebar badge; non-admins get 403."""
    from api.routes.feedback import feedback_summary
    from db.models import Feedback

    db, _, admin_id, user_id = db_with_users
    for status in ("needs_review", "failed", "new", "issue_created"):
        db.add(Feedback(user_id=user_id, kind="bug", message="x", status=status))
    db.commit()

    summary = feedback_summary(user_id=admin_id, db=db)
    assert summary["needs_review"] == 1
    assert summary["failed"] == 1
    assert summary["actionable"] == 2
    assert summary["total"] == 4

    with pytest.raises(HTTPException) as exc:
        feedback_summary(user_id=user_id, db=db)
    assert exc.value.status_code == 403

def test_empty_llm_output_does_not_drop_user_report(db_with_users, monkeypatch):
    """An empty LLM title/body must fall back to the rule-based body (which
    carries the real message) instead of publishing a contentless issue."""
    from api import feedback_triage as ft
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    monkeypatch.setenv("PRAXYS_FEEDBACK_AUTOFILE_WITHOUT_AI", "true")
    calls: list = []
    _stub_github(monkeypatch, calls)
    monkeypatch.setattr(ft.llm, "get_client", lambda: object())
    monkeypatch.setattr(
        ft.llm,
        "chat_json",
        lambda *a, **k: {"kind": "bug", "title": "", "body": "", "contains_sensitive": False},
    )
    row = _new_row(db, user_id, "Charts crash when I open Training")

    result = triage_and_publish(row.id, _session=db)
    # Empty model output is not trusted; the real message survives.
    assert result["used_llm"] is False
    assert len(calls) == 1
    assert "Charts crash" in calls[0]["body"]


def test_commit_failure_after_publish_recovers_issue_created(db_with_users, monkeypatch):
    """If the post-create commit fails, the row still ends issue_created (with
    the issue number) so a retry can't file a duplicate."""
    from api.feedback_triage import triage_and_publish
    from db.models import Feedback

    db, _, _, user_id = db_with_users
    monkeypatch.setenv("PRAXYS_FEEDBACK_AUTOFILE_WITHOUT_AI", "true")
    calls: list = []
    _stub_github(monkeypatch, calls)
    row = _new_row(db, user_id, "A clean bug report")
    fid = row.id

    real_commit = db.commit
    state = {"n": 0}

    def flaky_commit():
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("commit boom")
        return real_commit()

    monkeypatch.setattr(db, "commit", flaky_commit)
    result = triage_and_publish(fid, _session=db)

    assert result["status"] == "issue_created"
    assert len(calls) == 1  # issue created exactly once — no duplicate
    fresh = db.query(Feedback).filter(Feedback.id == fid).first()
    assert fresh.status == "issue_created"
    assert fresh.github_issue_number == 101

# ---------------------------------------------------------------------------
# GitHub App auth (no-rotation alternative to the PAT)
# ---------------------------------------------------------------------------


def _rsa_pem():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload
        self.reason_phrase = "OK"

    def json(self):
        return self._p


def test_github_app_mints_and_caches_installation_token(monkeypatch):
    from api import github_issues as gi

    monkeypatch.setenv("PRAXYS_FEEDBACK_GITHUB_REPO", "owner/repo")
    monkeypatch.setenv("PRAXYS_GITHUB_APP_ID", "123")
    monkeypatch.setenv("PRAXYS_GITHUB_APP_INSTALLATION_ID", "456")
    # single-line PEM with literal \n — the App Service storage shape
    monkeypatch.setenv("PRAXYS_GITHUB_APP_PRIVATE_KEY", _rsa_pem().replace("\n", "\\n"))
    gi._install_token.update({"token": None, "exp": 0.0})

    calls = {"mint": 0, "issue": 0}

    def fake_post(url, **kw):
        if url.endswith("/access_tokens"):
            calls["mint"] += 1
            assert kw["headers"]["Authorization"].startswith("Bearer ")
            return _FakeResp(201, {"token": "ghs_tok", "expires_at": "2999-01-01T00:00:00Z"})
        calls["issue"] += 1
        return _FakeResp(201, {"number": 9, "html_url": "https://x/9"})

    monkeypatch.setattr(gi.httpx, "post", fake_post)

    assert gi.is_configured() is True
    assert gi._bearer_token() == "ghs_tok"
    gi._bearer_token()  # cached — must not re-mint
    assert calls["mint"] == 1
    assert gi.create_issue(title="t", body="b", labels=["bug"]) == {"number": 9, "url": "https://x/9"}


def test_not_configured_without_creds(monkeypatch):
    from api import github_issues as gi

    for v in (
        "PRAXYS_GITHUB_APP_ID", "PRAXYS_GITHUB_APP_INSTALLATION_ID",
        "PRAXYS_GITHUB_APP_PRIVATE_KEY",
    ):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("PRAXYS_FEEDBACK_GITHUB_REPO", "owner/repo")
    assert gi.is_configured() is False

def test_github_app_malformed_mint_response_returns_none(monkeypatch):
    """A 201 with a non-JSON body must degrade to None, not raise out of
    _bearer_token (the admin approve route calls create_issue unguarded)."""
    from api import github_issues as gi

    monkeypatch.setenv("PRAXYS_FEEDBACK_GITHUB_REPO", "owner/repo")
    monkeypatch.setenv("PRAXYS_GITHUB_APP_ID", "1")
    monkeypatch.setenv("PRAXYS_GITHUB_APP_INSTALLATION_ID", "2")
    monkeypatch.setenv("PRAXYS_GITHUB_APP_PRIVATE_KEY", _rsa_pem())
    gi._install_token.update({"token": None, "exp": 0.0})

    class _BadResp:
        status_code = 201
        reason_phrase = "Created"

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(gi.httpx, "post", lambda url, **kw: _BadResp())
    assert gi._bearer_token() is None  # must not raise

# ---------------------------------------------------------------------------
# Sensitivity-gate calibration (over-flagging fix)
# ---------------------------------------------------------------------------


def test_system_prompt_defaults_sensitive_to_false():
    """The triage prompt must not bias the model toward flagging benign reports
    (regression for the 'when unsure, prefer true' over-flagging)."""
    from api.feedback_triage import _system_prompt

    p = _system_prompt()
    assert "prefer true" not in p.lower()
    assert "default to false" in p.lower()
    assert "always include the contains_sensitive" in p.lower()


def test_triage_uses_deterministic_temperature(db_with_users, monkeypatch):
    """Triage must call the model at temperature 0 so the sensitivity verdict
    doesn't vary run-to-run and rarely flip a benign report to sensitive."""
    from api import feedback_triage as ft
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    captured: dict = {}

    monkeypatch.setattr(ft.llm, "get_client", lambda: object())

    def fake_chat_json(client, **kwargs):
        captured.update(kwargs)
        return {"kind": "bug", "title": "T", "body": "B", "contains_sensitive": False}

    monkeypatch.setattr(ft.llm, "chat_json", fake_chat_json)
    row = _new_row(db, user_id, "charts render slowly on the training page")
    triage_and_publish(row.id, _session=db)
    assert captured.get("temperature") == 0.0


# ---------------------------------------------------------------------------
# Screenshot attachment: storage, vision triage, gate, admin serve (issue #337)
# ---------------------------------------------------------------------------

# A minimal valid 1x1 PNG — the magic bytes make sniff() detect image/png.
_PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)


def test_storage_sniff_validate_decode():
    from api import feedback_storage as fs

    assert fs.sniff(_PNG_1PX) == "image/png"
    assert fs.sniff(b"just some plain text, not an image at all") is None
    assert fs.validate_image(_PNG_1PX) == "image/png"
    # Oversize is rejected even though the magic bytes are valid.
    assert fs.validate_image(_PNG_1PX + b"\x00" * (fs.MAX_IMAGE_BYTES + 1)) is None
    # Both a data-URL and raw base64 decode to the same bytes.
    raw = base64.b64encode(_PNG_1PX).decode()
    assert fs.decode_base64_image(raw) == _PNG_1PX
    assert fs.decode_base64_image("data:image/png;base64," + raw) == _PNG_1PX
    assert fs.decode_base64_image("not!!valid!!base64") is None


def test_storage_roundtrip_and_key_safety(db_with_users):
    # db_with_users sets DATA_DIR to a temp dir → local filesystem backend.
    from api import feedback_storage as fs

    key = fs.store_image(_PNG_1PX, feedback_id=42, index=0)
    assert key == "feedback/42/0.png"
    got = fs.load_image(key)
    assert got is not None and got[0] == _PNG_1PX and got[1] == "image/png"
    # A tampered / traversal key is rejected outright.
    assert fs.load_image("feedback/../../secret") is None
    assert fs.load_image("feedback/42/0.exe") is None
    # Non-image bytes are never stored.
    assert fs.store_image(b"not an image", feedback_id=42, index=1) is None


def _row_with_image(db, user_id, message="broken chart on training page"):
    """Persist a feedback row with one real stored screenshot."""
    from api import feedback_storage as fs
    from db.models import Feedback

    row = Feedback(user_id=user_id, kind="bug", message=message, status="new")
    db.add(row)
    db.commit()
    db.refresh(row)
    key = fs.store_image(_PNG_1PX, feedback_id=row.id, index=0)
    row.image_keys = [key]
    db.commit()
    db.refresh(row)
    return row


def _stub_vision(monkeypatch, *, description, sensitive):
    from api import feedback_triage as ft

    monkeypatch.setattr(
        ft.feedback_vision,
        "analyze_images",
        lambda images: {"description": description, "sensitive": sensitive},
    )


# --- Submit endpoint: validation + storage ---------------------------------


def test_submit_stores_image_and_sets_keys(db_with_users):
    from api.routes.feedback import submit_feedback, FeedbackRequest
    from api import feedback_storage as fs
    from db.models import Feedback

    db, _, _, user_id = db_with_users
    b64 = base64.b64encode(_PNG_1PX).decode()
    resp = submit_feedback(
        FeedbackRequest(kind="bug", message="broken chart", images=[b64]),
        background_tasks=BackgroundTasks(),
        user_id=user_id,
        db=db,
    )
    row = db.query(Feedback).filter(Feedback.id == resp["id"]).first()
    assert row.image_keys == ["feedback/%d/0.png" % row.id]
    got = fs.load_image(row.image_keys[0])
    assert got is not None and got[0] == _PNG_1PX


def test_submit_rejects_non_image_before_persisting(db_with_users):
    from api.routes.feedback import submit_feedback, FeedbackRequest
    from db.models import Feedback

    db, _, _, user_id = db_with_users
    bad = base64.b64encode(b"definitely not an image file").decode()
    with pytest.raises(HTTPException) as exc:
        submit_feedback(
            FeedbackRequest(kind="bug", message="x", images=[bad]),
            background_tasks=BackgroundTasks(),
            user_id=user_id,
            db=db,
        )
    assert exc.value.status_code == 415
    # Nothing was persisted — validation runs before the row is created.
    assert db.query(Feedback).count() == 0


def test_submit_rejects_oversize_image(db_with_users):
    from api.routes.feedback import submit_feedback, FeedbackRequest
    from api import feedback_storage as fs

    db, _, _, user_id = db_with_users
    big = base64.b64encode(_PNG_1PX + b"\x00" * (fs.MAX_IMAGE_BYTES + 1)).decode()
    with pytest.raises(HTTPException) as exc:
        submit_feedback(
            FeedbackRequest(kind="bug", message="x", images=[big]),
            background_tasks=BackgroundTasks(),
            user_id=user_id,
            db=db,
        )
    assert exc.value.status_code == 413


def test_feedback_request_caps_image_count():
    """Pydantic caps the image count at the schema level (max_length)."""
    from api.routes.feedback import FeedbackRequest
    from pydantic import ValidationError

    b64 = base64.b64encode(_PNG_1PX).decode()
    with pytest.raises(ValidationError):
        FeedbackRequest(kind="bug", message="x", images=[b64, b64, b64, b64])


# --- Triage: vision fold + gate --------------------------------------------


def test_triage_folds_scrubbed_vision_description_and_publishes(db_with_users, monkeypatch):
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    calls: list = []
    _stub_github(monkeypatch, calls)
    _stub_llm(monkeypatch, sensitive=False)  # text path is clean
    _stub_vision(
        monkeypatch,
        description="The Training page shows a broken chart. Email shown: bob@example.com",
        sensitive=False,
    )
    row = _row_with_image(db, user_id)

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "issue_created"
    assert result["used_vision"] is True
    assert len(calls) == 1
    body = calls[0]["body"]
    # The scrubbed description is folded in with the admin-console reference...
    assert "## Screenshot" in body
    assert "admin console" in body
    assert "not published here" in body
    # ...and the vision text is re-scrubbed, so no raw PII reaches the issue.
    assert "bob@example.com" not in body
    assert "[redacted-email]" in body
    db.refresh(row)
    assert row.image_sensitive is False
    assert "[redacted-email]" in (row.image_description or "")
    assert "screenshot" in (row.ai_labels or [])


def test_triage_gate_holds_on_sensitive_image(db_with_users, monkeypatch):
    """Text may be clean, but a vision-flagged sensitive image parks the row."""
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    calls: list = []
    _stub_github(monkeypatch, calls)
    _stub_llm(monkeypatch, sensitive=False)
    _stub_vision(
        monkeypatch,
        description="A dashboard showing the user's face and heart-rate history",
        sensitive=True,
    )
    row = _row_with_image(db, user_id)

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "needs_review"
    assert calls == []  # the image is never published to a public issue
    db.refresh(row)
    assert row.image_sensitive is True


def test_triage_gate_holds_on_unverified_image_even_with_autofile(db_with_users, monkeypatch):
    """A screenshot present but not vision-verified (no model configured) parks
    the row, overriding the scrub-only autofile opt-in — an unread image is
    unsafe to auto-publish."""
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    monkeypatch.setenv("PRAXYS_FEEDBACK_AUTOFILE_WITHOUT_AI", "true")
    calls: list = []
    _stub_github(monkeypatch, calls)
    # db_with_users clears AZURE_AI_ENDPOINT, so analyze_images returns None.
    row = _row_with_image(db, user_id)

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "needs_review"
    assert calls == []
    db.refresh(row)
    assert row.image_sensitive is None


# --- Admin image serve ------------------------------------------------------


def test_admin_image_serve_and_404_and_authz(db_with_users):
    from api.routes.feedback import submit_feedback, get_feedback_image, FeedbackRequest
    from fastapi import Response

    db, _, admin_id, user_id = db_with_users
    b64 = base64.b64encode(_PNG_1PX).decode()
    fid = submit_feedback(
        FeedbackRequest(kind="bug", message="x", images=[b64]),
        background_tasks=BackgroundTasks(),
        user_id=user_id,
        db=db,
    )["id"]

    out = get_feedback_image(fid, 0, user_id=admin_id, db=db)
    assert isinstance(out, Response)
    assert out.body == _PNG_1PX
    assert out.media_type == "image/png"

    # Out-of-range index → 404.
    with pytest.raises(HTTPException) as exc:
        get_feedback_image(fid, 5, user_id=admin_id, db=db)
    assert exc.value.status_code == 404

    # A non-admin is refused before any image is served.
    with pytest.raises(HTTPException) as exc:
        get_feedback_image(fid, 0, user_id=user_id, db=db)
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Priority auto-suggestion (issue #359)
# ---------------------------------------------------------------------------


def test_triage_assigns_priority_from_llm(db_with_users, monkeypatch):
    """The LLM's suggested priority lands on the row and a mirroring label."""
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    calls: list = []
    _stub_github(monkeypatch, calls)
    _stub_llm(monkeypatch, sensitive=False, priority="high")
    row = _new_row(db, user_id, "Charts fail to load on the training page")

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "issue_created"
    db.refresh(row)
    assert row.priority == "high"
    assert "priority: high" in (row.ai_labels or [])
    assert "priority: high" in calls[0]["labels"]


def test_triage_ignores_invalid_priority(db_with_users, monkeypatch):
    """A priority outside the allowed set is dropped (no label, NULL column)."""
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    calls: list = []
    _stub_github(monkeypatch, calls)
    _stub_llm(monkeypatch, sensitive=False, priority="urgent")  # not a valid bucket
    row = _new_row(db, user_id, "Charts fail to load on the training page")

    triage_and_publish(row.id, _session=db)
    db.refresh(row)
    assert row.priority is None
    assert not any(str(lbl).startswith("priority:") for lbl in (row.ai_labels or []))


def test_triage_priority_none_without_llm(db_with_users):
    """No LLM configured → rule-based triage leaves priority unset."""
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    row = _new_row(db, user_id, "Some report with no AI available")

    triage_and_publish(row.id, _session=db)
    db.refresh(row)
    assert row.priority is None


# ---------------------------------------------------------------------------
# Change loop: agent-ready gating for the Copilot coding agent (issue #362)
# ---------------------------------------------------------------------------

_DETAILED_BUG = "The training charts fail to render after a sync completes"
_DETAILED_CJK_BUG = "今日页面状态建议休息，但 Praxys 教练建议完成长距离训练，两条建议相互矛盾"


def test_triage_tags_agent_ready_for_qualifying_bug(db_with_users, monkeypatch):
    """A clean, detailed bug earns agent-ready -- on the row and the filed issue."""
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    calls: list = []
    _stub_github(monkeypatch, calls)
    _stub_llm(monkeypatch, sensitive=False)
    row = _new_row(db, user_id, _DETAILED_BUG)

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "issue_created"
    assert result["agent_ready"] is True
    db.refresh(row)
    assert "agent-ready" in (row.ai_labels or [])
    assert "agent-ready" in calls[0]["labels"]


def test_triage_tags_agent_ready_for_detailed_cjk_bug(db_with_users, monkeypatch):
    """Detailed feedback without whitespace word boundaries still qualifies."""
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    calls: list = []
    _stub_github(monkeypatch, calls)
    _stub_llm(monkeypatch, sensitive=False)
    row = _new_row(db, user_id, _DETAILED_CJK_BUG)

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "issue_created"
    assert result["agent_ready"] is True
    db.refresh(row)
    assert "agent-ready" in (row.ai_labels or [])
    assert "agent-ready" in calls[0]["labels"]


def test_triage_no_agent_ready_for_feature(db_with_users, monkeypatch):
    """Features are assist-not-act: published, but never auto-assigned."""
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    calls: list = []
    _stub_github(monkeypatch, calls)
    _stub_llm(monkeypatch, sensitive=False, kind="feature", agent_eligible=False)
    row = _new_row(
        db, user_id, "Please add a weekly mileage target to the goal page", kind="feature"
    )

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "issue_created"
    db.refresh(row)
    assert "agent-ready" not in (row.ai_labels or [])
    assert "agent-ready" not in calls[0]["labels"]


def test_triage_no_agent_ready_when_sensitive(db_with_users, monkeypatch):
    """A gated (sensitive) report is parked and never tagged agent-ready. The
    label never even lands in ai_labels, so a later admin approve can't assign."""
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    calls: list = []
    _stub_github(monkeypatch, calls)
    _stub_llm(monkeypatch, sensitive=True)
    row = _new_row(db, user_id, _DETAILED_BUG)

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "needs_review"
    assert calls == []  # nothing published
    db.refresh(row)
    assert "agent-ready" not in (row.ai_labels or [])


@pytest.mark.parametrize("message", ["totally broken", "页面坏了"])
def test_triage_no_agent_ready_for_low_detail_bug(db_with_users, monkeypatch, message):
    """A terse bug is published but too thin to hand to the coding agent."""
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    calls: list = []
    _stub_github(monkeypatch, calls)
    _stub_llm(monkeypatch, sensitive=False)
    row = _new_row(db, user_id, message)

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "issue_created"
    db.refresh(row)
    assert "agent-ready" not in (row.ai_labels or [])


def test_triage_no_agent_ready_without_ai_gate(db_with_users, monkeypatch):
    """No AI to judge sensitivity -> the report is parked, not agent-tagged."""
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    calls: list = []
    _stub_github(monkeypatch, calls)  # GitHub configured, but no LLM stub
    row = _new_row(db, user_id, _DETAILED_BUG)

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "needs_review"
    assert calls == []
    db.refresh(row)
    assert "agent-ready" not in (row.ai_labels or [])


def test_triage_no_agent_ready_when_not_actionable_bug(db_with_users, monkeypatch):
    """A bug-shaped report the model judges not actionable (works-as-intended, a
    support question, too vague) is published but never handed to the agent."""
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    calls: list = []
    _stub_github(monkeypatch, calls)
    _stub_llm(monkeypatch, sensitive=False, agent_eligible=False)
    row = _new_row(db, user_id, _DETAILED_BUG)

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "issue_created"
    assert result["agent_ready"] is False
    db.refresh(row)
    assert "agent-ready" not in (row.ai_labels or [])
    assert "agent-ready" not in calls[0]["labels"]


def test_triage_shadow_mode_withholds_agent_ready(db_with_users, monkeypatch):
    """Shadow mode computes the decision but never applies the label, so a
    qualifying bug is filed without auto-assigning the coding agent."""
    from api.feedback_triage import triage_and_publish

    db, _, _, user_id = db_with_users
    monkeypatch.setenv("PRAXYS_AGENT_READY_SHADOW", "true")
    calls: list = []
    _stub_github(monkeypatch, calls)
    _stub_llm(monkeypatch, sensitive=False)  # would otherwise qualify
    row = _new_row(db, user_id, _DETAILED_BUG)

    result = triage_and_publish(row.id, _session=db)
    assert result["status"] == "issue_created"
    assert result["agent_ready"] is False
    db.refresh(row)
    assert "agent-ready" not in (row.ai_labels or [])
    assert "agent-ready" not in calls[0]["labels"]


# ---------------------------------------------------------------------------
# GitHub issue status sync (issue #359)
# ---------------------------------------------------------------------------


def _stub_issue_state(monkeypatch, mapping):
    """Stub github_issues so get_issue_state returns the mapped open/closed."""
    from api import github_issues

    monkeypatch.setattr(github_issues, "is_configured", lambda: True)

    def _state(number):
        st = mapping.get(number)
        return {"state": st, "state_reason": None} if st else None

    monkeypatch.setattr(github_issues, "get_issue_state", _state)


def test_sync_marks_resolved_when_issue_closed(db_with_users, monkeypatch):
    from api.routes.feedback import sync_feedback_status
    from db.models import Feedback

    db, _, admin_id, user_id = db_with_users
    row = Feedback(user_id=user_id, kind="bug", message="x", status="issue_created", github_issue_number=101)
    db.add(row)
    db.commit()
    db.refresh(row)

    _stub_issue_state(monkeypatch, {101: "closed"})
    out = sync_feedback_status(user_id=admin_id, db=db)
    assert out == {"configured": True, "checked": 1, "updated": 1}
    db.refresh(row)
    assert row.status == "resolved"


def test_sync_reopens_resolved_when_issue_open(db_with_users, monkeypatch):
    from api.routes.feedback import sync_feedback_status
    from db.models import Feedback

    db, _, admin_id, user_id = db_with_users
    row = Feedback(user_id=user_id, kind="bug", message="x", status="resolved", github_issue_number=55)
    db.add(row)
    db.commit()
    db.refresh(row)

    _stub_issue_state(monkeypatch, {55: "open"})
    out = sync_feedback_status(user_id=admin_id, db=db)
    assert out["updated"] == 1
    db.refresh(row)
    assert row.status == "issue_created"


def test_sync_only_touches_linked_in_flight_rows(db_with_users, monkeypatch):
    """Triage-side and unlinked rows are never queried or mutated."""
    from api.routes.feedback import sync_feedback_status
    from db.models import Feedback

    db, _, admin_id, user_id = db_with_users
    linked = Feedback(user_id=user_id, kind="bug", message="x", status="issue_created", github_issue_number=101)
    pending = Feedback(user_id=user_id, kind="bug", message="y", status="needs_review")
    fresh = Feedback(user_id=user_id, kind="bug", message="z", status="new")
    declined = Feedback(user_id=user_id, kind="bug", message="w", status="rejected", github_issue_number=9)
    db.add_all([linked, pending, fresh, declined])
    db.commit()

    _stub_issue_state(monkeypatch, {101: "closed"})
    out = sync_feedback_status(user_id=admin_id, db=db)
    assert out == {"configured": True, "checked": 1, "updated": 1}
    for r in (linked, pending, fresh, declined):
        db.refresh(r)
    assert linked.status == "resolved"
    assert pending.status == "needs_review"
    assert fresh.status == "new"
    assert declined.status == "rejected"


def test_sync_noop_when_github_not_configured(db_with_users, monkeypatch):
    from api.routes.feedback import sync_feedback_status
    from api import github_issues
    from db.models import Feedback

    db, _, admin_id, user_id = db_with_users
    db.add(Feedback(user_id=user_id, kind="bug", message="x", status="issue_created", github_issue_number=7))
    db.commit()

    monkeypatch.setattr(github_issues, "is_configured", lambda: False)
    out = sync_feedback_status(user_id=admin_id, db=db)
    assert out == {"configured": False, "checked": 0, "updated": 0}


def test_sync_requires_admin(db_with_users):
    from api.routes.feedback import sync_feedback_status

    db, _, _, user_id = db_with_users
    with pytest.raises(HTTPException) as exc:
        sync_feedback_status(user_id=user_id, db=db)
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# Status filtering (issue #359)
# ---------------------------------------------------------------------------


def test_list_active_filter_excludes_terminal(db_with_users):
    from api.routes.feedback import list_feedback
    from db.models import Feedback

    db, _, admin_id, user_id = db_with_users
    for st in ("new", "issue_created", "resolved", "rejected", "needs_review", "failed"):
        db.add(Feedback(user_id=user_id, kind="bug", message="x", status=st))
    db.commit()

    active = list_feedback(status="active", user_id=admin_id, db=db)
    statuses = {r["status"] for r in active}
    assert "resolved" not in statuses
    assert "rejected" not in statuses
    assert {"new", "issue_created", "needs_review", "failed"} <= statuses
    # priority is exposed in the serialized row.
    assert "priority" in active[0]

    # An exact status still filters precisely, including the new resolved value.
    only_resolved = list_feedback(status="resolved", user_id=admin_id, db=db)
    assert len(only_resolved) == 1
    assert only_resolved[0]["status"] == "resolved"


def test_retry_and_approve_blocked_on_linked_resolved_row(db_with_users):
    """A resolved ticket still owns a live GitHub issue — retry/approve must be
    refused so we never file a duplicate on the public tracker (issue #359)."""
    from api.routes.feedback import update_feedback, FeedbackAction
    from db.models import Feedback

    db, _, admin_id, user_id = db_with_users
    row = Feedback(
        user_id=user_id,
        kind="bug",
        message="x",
        status="resolved",
        github_issue_number=101,
        github_issue_url="https://github.com/x/y/issues/101",
        ai_title="t",
        ai_body="b",
        ai_labels=["bug", "feedback"],
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    for action in ("retry", "approve"):
        bg = BackgroundTasks()
        with pytest.raises(HTTPException) as exc:
            update_feedback(row.id, FeedbackAction(action=action), bg, user_id=admin_id, db=db)
        assert exc.value.status_code == 409, action
        assert len(bg.tasks) == 0, action

    # Untouched: still resolved and linked to the original issue (no duplicate).
    db.refresh(row)
    assert row.status == "resolved"
    assert row.github_issue_number == 101