"""AI insights endpoints — push from CLI, retrieve for web display."""
import logging
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from api import telemetry
from api.auth import get_current_user_id, get_data_user_id, require_write_access
from api.insight_feedback import (
    GENERATION_PROVENANCE_KEY,
    feedback_payload as _feedback_payload,
    feedback_state as _feedback_state,
    feedback_telemetry_dimensions as _feedback_telemetry_dimensions,
    is_dataset_hash as _is_dataset_hash,
    merge_feedback_meta as _merge_feedback_meta,
)
from api.auth_rate_limit import _SlidingWindow
from api.views import utc_isoformat
from db.session import begin_serialized_write, get_db

logger = logging.getLogger(__name__)

router = APIRouter()

VALID_INSIGHT_TYPES = {"training_review", "daily_brief", "race_forecast"}
_INSIGHT_FEEDBACK_RATE_LIMIT = _SlidingWindow(
    limit=12, window_secs=60, max_clients=10_000
)


def _lock_active_user(db: Session, user_id: str) -> None:
    """Lock the account before any insight child-row write."""
    from db.models import User

    user = (
        db.query(User)
        .populate_existing()
        .with_for_update()
        .filter(User.id == user_id)
        .first()
    )
    if user is None or not user.is_active:
        db.rollback()
        raise HTTPException(401, detail="UNAUTHORIZED")


def _serialize_meta(value: object, *, feedback_allowed: bool) -> dict[str, Any]:
    """Sanitize known metadata fields while retaining unknown legacy keys."""
    meta = dict(value) if isinstance(value, dict) else {}
    meta.pop(GENERATION_PROVENANCE_KEY, None)
    if not isinstance(meta.get("dataset_hash"), str):
        meta.pop("dataset_hash", None)
    if not isinstance(meta.get("model"), str):
        meta.pop("model", None)
    pillars = meta.get("pillars")
    if not (
        isinstance(pillars, dict)
        and all(isinstance(key, str) and isinstance(item, str) for key, item in pillars.items())
    ):
        meta.pop("pillars", None)

    feedback = _feedback_state(meta.get("feedback"), meta.get("dataset_hash"))
    if feedback_allowed and feedback is not None:
        meta["feedback"] = feedback
    else:
        meta.pop("feedback", None)
    return meta


def _serialize_insight(
    row: Any,
    db: Session,
    *,
    feedback_allowed: bool,
) -> dict[str, Any]:
    """Serialize one insight with server-derived feedback eligibility."""
    meta = row.meta
    if feedback_allowed and isinstance(meta, dict):
        meta = _merge_feedback_meta(
            db,
            row.user_id,
            row.insight_type,
            meta,
            meta,
        )
    return {
        "headline": row.headline,
        "summary": row.summary,
        "findings": row.findings or [],
        "recommendations": row.recommendations or [],
        "meta": _serialize_meta(meta, feedback_allowed=feedback_allowed),
        "translations": row.translations or {},
        "generated_at": utc_isoformat(row.generated_at),
        "feedback_allowed": feedback_allowed,
    }


class InsightFinding(BaseModel):
    type: str  # positive, warning, neutral
    text: str


class PushInsightRequest(BaseModel):
    insight_type: str
    headline: str
    summary: str
    findings: list[InsightFinding] = []
    recommendations: list[str] = []
    meta: dict[str, Any] = {}
    # Optional bilingual payload — written by the post-sync LLM runner.
    # Legacy CLI / MCP push paths may omit this; old rows render English from
    # the top-level fields. Issue #103.
    translations: dict = {}


class InsightFeedbackRequest(BaseModel):
    """One vote on the exact generated insight version the athlete saw."""

    model_config = ConfigDict(extra="forbid")

    vote: Literal["up", "down"]
    dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    comment: str | None = Field(default=None, max_length=200)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        """Normalize blank comments to ``None`` without retaining raw text."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

@router.post("/insights")
def push_insight(
    body: PushInsightRequest,
    user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
) -> dict:
    """Push AI-generated insights (from CLI skills). Upserts per insight_type."""
    if body.insight_type not in VALID_INSIGHT_TYPES:
        raise HTTPException(400, f"Invalid insight_type. Must be one of: {VALID_INSIGHT_TYPES}")

    from db.models import AiInsight

    begin_serialized_write(db)
    _lock_active_user(db, user_id)
    existing = (
        db.query(AiInsight)
        .with_for_update()
        .filter(
            AiInsight.user_id == user_id,
            AiInsight.insight_type == body.insight_type,
        )
        .first()
    )

    findings_dicts = [f.model_dump() for f in body.findings]
    client_meta = dict(body.meta)
    client_meta.pop(GENERATION_PROVENANCE_KEY, None)
    incoming_meta = _merge_feedback_meta(
        db,
        user_id,
        body.insight_type,
        client_meta,
        existing.meta if existing is not None else None,
    )

    if existing:
        existing.headline = body.headline
        existing.summary = body.summary
        existing.findings = findings_dicts
        existing.recommendations = body.recommendations
        existing.meta = incoming_meta
        existing.translations = body.translations
        existing.generated_at = datetime.utcnow()
    else:
        db.add(AiInsight(
            user_id=user_id,
            insight_type=body.insight_type,
            headline=body.headline,
            summary=body.summary,
            findings=findings_dicts,
            recommendations=body.recommendations,
            meta=incoming_meta,
            translations=body.translations,
        ))

    db.commit()
    return {"status": "saved", "insight_type": body.insight_type}


@router.post("/insights/{insight_type}/feedback")
def submit_insight_feedback(
    insight_type: str,
    body: InsightFeedbackRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Persist idempotency state and emit a privacy-scrubbed Coach vote."""
    if insight_type not in VALID_INSIGHT_TYPES:
        raise HTTPException(
            400,
            detail=f"Invalid insight_type. Must be one of: {VALID_INSIGHT_TYPES}",
        )
    allowed, retry_after = _INSIGHT_FEEDBACK_RATE_LIMIT.check_and_record(user_id)
    if not allowed:
        raise HTTPException(
            429,
            detail="INSIGHT_FEEDBACK_RATE_LIMITED",
            headers={"Retry-After": str(retry_after)},
        )

    from db.models import AiInsight, AiInsightFeedback

    begin_serialized_write(db)
    _lock_active_user(db, user_id)
    row = (
        db.query(AiInsight)
        .with_for_update()
        .filter(
            AiInsight.user_id == user_id,
            AiInsight.insight_type == insight_type,
        )
        .first()
    )
    if row is None:
        raise HTTPException(404, detail="INSIGHT_NOT_FOUND")

    meta = dict(row.meta or {})
    current_hash = meta.get("dataset_hash")
    if not _is_dataset_hash(current_hash):
        raise HTTPException(409, detail="INSIGHT_FEEDBACK_UNVERSIONED")
    if body.dataset_hash != current_hash:
        raise HTTPException(409, detail="INSIGHT_FEEDBACK_STALE")

    existing_row = db.query(AiInsightFeedback).filter(
        AiInsightFeedback.user_id == user_id,
        AiInsightFeedback.insight_type == insight_type,
        AiInsightFeedback.dataset_hash == current_hash,
    ).first()
    if existing_row is not None:
        feedback = _feedback_payload(existing_row)
        if _feedback_state(meta.get("feedback"), current_hash) != feedback:
            meta["feedback"] = feedback
            row.meta = meta
            try:
                db.commit()
            except Exception:
                db.rollback()
                logger.exception("Failed to restore %s insight feedback", insight_type)
                raise HTTPException(500, detail="INSIGHT_FEEDBACK_SAVE_FAILED")
        else:
            db.rollback()
        return {"accepted": True, "duplicate": True, "feedback": feedback}

    telemetry_model, telemetry_pillars = _feedback_telemetry_dimensions(meta)

    submitted_at = datetime.now(timezone.utc)
    feedback_row = AiInsightFeedback(
        user_id=user_id,
        insight_type=insight_type,
        dataset_hash=current_hash,
        vote=body.vote,
        submitted_at=submitted_at.replace(tzinfo=None),
    )
    feedback = {
        "dataset_hash": current_hash,
        "vote": body.vote,
        "submitted_at": utc_isoformat(submitted_at),
    }
    db.add(feedback_row)
    meta["feedback"] = feedback
    row.meta = meta
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to save %s insight feedback", insight_type)
        raise HTTPException(500, detail="INSIGHT_FEEDBACK_SAVE_FAILED")

    telemetry.record_coach_feedback(
        insight_type=insight_type,
        dataset_hash=current_hash,
        model=telemetry_model,
        pillars=telemetry_pillars,
        vote=body.vote,
        comment=body.comment,
        user_id=user_id,
    )
    return {"accepted": True, "duplicate": False, "feedback": feedback}

@router.get("/insights")
def get_insights(
    current_user_id: str = Depends(get_current_user_id),
    data_user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Get all AI insights for the current user."""
    from db.models import AiInsight

    feedback_allowed = current_user_id == data_user_id
    rows = db.query(AiInsight).filter(AiInsight.user_id == data_user_id).all()
    return {
        "insights": {
            row.insight_type: _serialize_insight(
                row,
                db,
                feedback_allowed=feedback_allowed,
            )
            for row in rows
        }
    }


@router.get("/insights/{insight_type}")
def get_insight(
    insight_type: str,
    current_user_id: str = Depends(get_current_user_id),
    data_user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Get a specific AI insight by type."""
    from db.models import AiInsight

    row = db.query(AiInsight).filter(
        AiInsight.user_id == data_user_id,
        AiInsight.insight_type == insight_type,
    ).first()

    if not row:
        return {"insight": None}

    return {
        "insight": _serialize_insight(
            row,
            db,
            feedback_allowed=current_user_id == data_user_id,
        )
    }