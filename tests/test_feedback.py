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
    monkeypatch.delenv("PRAXYS_GITHUB_TOKEN", raising=False)
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