"""AI insights endpoints — push from CLI, retrieve for web display."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_data_user_id, require_write_access
from api.views import utc_isoformat
from db.session import get_db

router = APIRouter()

VALID_INSIGHT_TYPES = {"training_review", "daily_brief", "race_forecast"}


class InsightFinding(BaseModel):
    type: str  # positive, warning, neutral
    text: str


class PushInsightRequest(BaseModel):
    insight_type: str
    headline: str
    summary: str
    findings: list[InsightFinding] = []
    recommendations: list[str] = []
    meta: dict = {}


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

    existing = db.query(AiInsight).filter(
        AiInsight.user_id == user_id,
        AiInsight.insight_type == body.insight_type,
    ).first()

    findings_dicts = [f.model_dump() for f in body.findings]

    if existing:
        existing.headline = body.headline
        existing.summary = body.summary
        existing.findings = findings_dicts
        existing.recommendations = body.recommendations
        existing.meta = body.meta
        existing.generated_at = datetime.utcnow()
    else:
        db.add(AiInsight(
            user_id=user_id,
            insight_type=body.insight_type,
            headline=body.headline,
            summary=body.summary,
            findings=findings_dicts,
            recommendations=body.recommendations,
            meta=body.meta,
        ))

    db.commit()
    return {"status": "saved", "insight_type": body.insight_type}


@router.get("/insights")
def get_insights(
    user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Get all AI insights for the current user."""
    from db.models import AiInsight

    rows = db.query(AiInsight).filter(AiInsight.user_id == user_id).all()
    return {
        "insights": {
            row.insight_type: {
                "headline": row.headline,
                "summary": row.summary,
                "findings": row.findings or [],
                "recommendations": row.recommendations or [],
                "meta": row.meta or {},
                "generated_at": utc_isoformat(row.generated_at),
            }
            for row in rows
        }
    }


@router.get("/insights/{insight_type}")
def get_insight(
    insight_type: str,
    user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Get a specific AI insight by type."""
    from db.models import AiInsight

    row = db.query(AiInsight).filter(
        AiInsight.user_id == user_id,
        AiInsight.insight_type == insight_type,
    ).first()

    if not row:
        return {"insight": None}

    return {
        "insight": {
            "headline": row.headline,
            "summary": row.summary,
            "findings": row.findings or [],
            "recommendations": row.recommendations or [],
            "meta": row.meta or {},
            "generated_at": utc_isoformat(row.generated_at),
        }
    }
