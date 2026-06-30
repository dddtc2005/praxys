"""Feedback endpoints — in-app bug reports / feature requests / general feedback.

POST   /api/feedback              — any authenticated user; stores + triages
GET    /api/admin/feedback        — admin only; list submissions
PATCH  /api/admin/feedback/{id}   — admin only; retry triage or reject

The submit handler does the minimum synchronously (validate, persist, emit a
telemetry signal) and hands the slow work — AI rewrite + PII scrub + GitHub
issue creation — to a background task (:func:`api.feedback_triage.triage_and_publish`)
so the user gets an instant 200. See that module for the pipeline.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api import telemetry
from api.auth import get_current_user_id
from api.feedback_triage import triage_and_publish
from api.views import require_admin, utc_isoformat
from db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

# Lightweight anti-spam: cap submissions per user in a sliding window. The
# auth-rate-limit middleware guards the unauthenticated surface; this guards an
# authenticated user from flooding the triage pipeline (and our LLM/GitHub
# spend) by holding the submit button.
_MAX_PER_WINDOW = 5
_WINDOW = timedelta(minutes=5)


class FeedbackRequest(BaseModel):
    """A single feedback submission."""

    kind: Literal["bug", "feature", "other"] = "other"
    message: str = Field(min_length=1, max_length=5000)
    # Free-form client diagnostic context (page, app_version, user_agent,
    # viewport, locale). Scrubbed to an allowlist before anything is published.
    context: dict[str, Any] | None = None
    locale: str = Field(default="", max_length=10)


@router.post("/feedback")
def submit_feedback(
    body: FeedbackRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Record a feedback submission and schedule background triage."""
    from db.models import Feedback

    cutoff = datetime.utcnow() - _WINDOW
    recent = (
        db.query(Feedback)
        .filter(Feedback.user_id == user_id, Feedback.created_at >= cutoff)
        .count()
    )
    if recent >= _MAX_PER_WINDOW:
        raise HTTPException(429, detail="FEEDBACK_RATE_LIMITED")

    try:
        row = Feedback(
            user_id=user_id,
            kind=body.kind,
            message=body.message,
            context_json=body.context or None,
            locale=body.locale or None,
            status="new",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        logger.exception("feedback save failed for user %s", user_id)
        raise HTTPException(500, detail="FEEDBACK_SAVE_FAILED")

    telemetry.record_feedback(kind=body.kind, status="new")
    background_tasks.add_task(triage_and_publish, row.id)
    logger.info("feedback submitted: id=%s kind=%s", row.id, body.kind)
    return {"ok": True, "id": row.id, "status": "received"}


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


def _serialize_admin(row) -> dict:
    """Full serialization for the Admin view — includes the raw message so an
    admin can see exactly what was reported, alongside the scrubbed output."""
    return {
        "id": row.id,
        "user_id": row.user_id,
        "kind": row.kind,
        "message": row.message,
        "context": row.context_json or {},
        "locale": row.locale,
        "status": row.status,
        "ai_title": row.ai_title,
        "ai_body": row.ai_body,
        "ai_labels": row.ai_labels or [],
        "github_issue_number": row.github_issue_number,
        "github_issue_url": row.github_issue_url,
        "error": row.error,
        "created_at": utc_isoformat(row.created_at),
        "updated_at": utc_isoformat(row.updated_at),
    }


@router.get("/admin/feedback")
def list_feedback(
    status: Optional[str] = None,
    limit: int = 100,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> list[dict]:
    """List feedback submissions, newest first. Admin only."""
    require_admin(user_id, db)
    from db.models import Feedback

    q = db.query(Feedback)
    if status:
        q = q.filter(Feedback.status == status)
    rows = q.order_by(Feedback.created_at.desc()).limit(min(max(limit, 1), 500)).all()
    return [_serialize_admin(r) for r in rows]


@router.get("/admin/feedback/summary")
def feedback_summary(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Counts by status for the admin notification badge. Admin only.

    ``actionable`` = needs_review + failed — the rows an admin should look at.
    Kept cheap (a single grouped count) so the sidebar can poll it.
    """
    require_admin(user_id, db)
    from sqlalchemy import func

    from db.models import Feedback

    rows = db.query(Feedback.status, func.count(Feedback.id)).group_by(Feedback.status).all()
    counts = {status: int(n) for status, n in rows}
    needs_review = counts.get("needs_review", 0)
    failed = counts.get("failed", 0)
    return {
        "needs_review": needs_review,
        "failed": failed,
        "new": counts.get("new", 0),
        "actionable": needs_review + failed,
        "total": sum(counts.values()),
    }


class FeedbackAction(BaseModel):
    """Admin action on a feedback row."""

    action: Literal["retry", "reject", "approve"]


@router.patch("/admin/feedback/{feedback_id}")
def update_feedback(
    feedback_id: int,
    payload: FeedbackAction,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Retry triage (re-publish) or reject a feedback row. Admin only."""
    require_admin(user_id, db)
    from db.models import Feedback

    row = db.query(Feedback).filter(Feedback.id == feedback_id).first()
    if not row:
        raise HTTPException(404, "Feedback not found")

    if payload.action == "reject":
        row.status = "rejected"
        row.error = None
        db.commit()
        return _serialize_admin(row)

    if payload.action == "approve":
        # Human override of the sensitivity gate: publish the already-scrubbed,
        # admin-reviewed title/body to GitHub. Used to release a needs_review row.
        if row.status == "issue_created":
            raise HTTPException(409, "Already published to GitHub")
        if not row.ai_title or not row.ai_body:
            raise HTTPException(409, "Nothing to publish yet — run triage first")
        from api import github_issues

        if not github_issues.is_configured():
            raise HTTPException(400, "GitHub is not configured")
        issue = github_issues.create_issue(
            title=row.ai_title,
            body=row.ai_body,
            labels=list(row.ai_labels or []),
        )
        if not issue or not issue.get("number"):
            row.status = "failed"
            row.error = "github_publish_failed"
            db.commit()
            raise HTTPException(502, "GitHub publish failed")
        row.github_issue_number = issue["number"]
        row.github_issue_url = issue.get("url")
        row.status = "issue_created"
        row.error = None
        db.commit()
        return _serialize_admin(row)

    # retry: reset to a re-triageable state and re-schedule. Guarded so an
    # already-published row isn't double-filed.
    if row.status == "issue_created":
        raise HTTPException(409, "Already published to GitHub")
    row.status = "new"
    row.error = None
    db.commit()
    background_tasks.add_task(triage_and_publish, row.id)
    return _serialize_admin(row)
