"""Tests for the in-app feedback feature.

Covers the deterministic PII scrub, the submit endpoint (persist + schedule +
rate-limit), the background triage pipeline (scrub-before-publish + the
no-GitHub "triaged" terminal state), and the admin list / retry / reject
actions. Route functions are called directly (passing user_id + db) — the same
dependency-bypass pattern as tests/test_announcements.py.
"""
from __future__ import annotations

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


def _stub_llm(monkeypatch, *, sensitive):
    from api import feedback_triage as ft

    monkeypatch.setattr(ft.llm, "get_client", lambda: object())
    monkeypatch.setattr(
        ft.llm,
        "chat_json",
        lambda *a, **k: {
            "kind": "bug",
            "title": "Charts crash on Training",
            "body": "The training charts fail to render.",
            "contains_sensitive": sensitive,
        },
    )


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

    # Retrying an already-published row is a conflict.
    row = db.query(Feedback).filter(Feedback.id == fid).first()
    row.status = "issue_created"
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