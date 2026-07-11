"""Authenticated product-behavior events shared by web and miniapp."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Self

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api import telemetry
from api.auth import get_current_user_id
from api.auth_rate_limit import _SlidingWindow
from api.version import is_valid_build_version
from db.session import begin_serialized_write, get_db

logger = logging.getLogger(__name__)
router = APIRouter()

ProductEventName = Literal[
    "app_opened",
    "today_brief_rendered",
    "today_reasoning_opened",
    "today_feedback_shown",
    "today_feedback_submitted",
]
TodayFeedbackResponse = Literal[
    "changed_plan",
    "confirmed_plan",
    "not_helpful",
    "not_training",
]

_EVENT_RATE_LIMIT = _SlidingWindow(limit=60, window_secs=60, max_clients=10_000)
_EVENT_DEDUP = _SlidingWindow(limit=1, window_secs=5, max_clients=50_000)
_TODAY_FEEDBACK_CADENCE = timedelta(days=7)
_TODAY_FEEDBACK_CLAIM_TTL = timedelta(minutes=2)
_TODAY_FEEDBACK_RESPONSE_TTL = _TODAY_FEEDBACK_CADENCE


class ProductEventRequest(BaseModel):
    """One allowlisted product event from an authenticated client."""

    model_config = ConfigDict(extra="forbid")

    event_name: ProductEventName
    surface: Literal["web", "miniapp"]
    app_version: str = Field(min_length=1, max_length=64)
    response: TodayFeedbackResponse | None = None

    @field_validator("app_version", mode="before")
    @classmethod
    def normalize_app_version(cls, value: object) -> str:
        """Accept only trimmed, low-cardinality build identifiers."""
        if not isinstance(value, str):
            raise ValueError("app_version must be a string")
        normalized = value.strip()
        if not is_valid_build_version(normalized):
            raise ValueError("app_version must be a build identifier")
        return normalized

    @model_validator(mode="after")
    def validate_response_shape(self) -> Self:
        """Keep response values exclusive to Decision Check submissions."""
        if self.event_name == "today_feedback_submitted":
            if self.response is None:
                raise ValueError("response is required for today_feedback_submitted")
        elif self.response is not None:
            raise ValueError("response is only valid for today_feedback_submitted")
        return self


def _locked_user_config(
    db: Session,
    user_id: str,
    *,
    create: bool,
) -> Any | None:
    """Lock the account and return its config for a cadence transition."""
    from db.models import User, UserConfig

    begin_serialized_write(db)
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

    config = (
        db.query(UserConfig)
        .with_for_update()
        .filter(UserConfig.user_id == user_id)
        .first()
    )
    if config is None and create:
        config = UserConfig(user_id=user_id)
        db.add(config)
    return config


def _commit_cadence(db: Session) -> None:
    """Commit a cadence transition with an explicit API error on failure."""
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to save Today Decision Check cadence")
        raise HTTPException(500, detail="PRODUCT_EVENT_CADENCE_SAVE_FAILED")


def _claim_today_feedback_prompt(db: Session, user_id: str) -> bool:
    """Reserve a short render window without counting the prompt as shown."""
    config = _locked_user_config(db, user_id, create=True)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    last_shown = config.today_decision_check_shown_at
    claimed_at = config.today_decision_check_claimed_at
    if (
        last_shown is not None
        and now - last_shown < _TODAY_FEEDBACK_CADENCE
    ) or (
        claimed_at is not None
        and now - claimed_at < _TODAY_FEEDBACK_CLAIM_TTL
    ):
        db.rollback()
        return False

    config.today_decision_check_claimed_at = now
    _commit_cadence(db)
    return True


def _confirm_today_feedback_prompt(
    db: Session,
    user_id: str,
) -> Literal["confirmed", "duplicate", "invalid"]:
    """Finalize a recent claim after render, with idempotent retries."""
    config = _locked_user_config(db, user_id, create=False)
    if config is None:
        db.rollback()
        return "invalid"

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    claimed_at = config.today_decision_check_claimed_at
    if (
        claimed_at is not None
        and now - claimed_at < _TODAY_FEEDBACK_CLAIM_TTL
    ):
        config.today_decision_check_claimed_at = None
        config.today_decision_check_shown_at = now
        _commit_cadence(db)
        return "confirmed"

    changed = False
    if claimed_at is not None:
        config.today_decision_check_claimed_at = None
        changed = True

    shown_at = config.today_decision_check_shown_at
    if shown_at is not None and now - shown_at < _TODAY_FEEDBACK_CLAIM_TTL:
        if changed:
            _commit_cadence(db)
        else:
            db.rollback()
        return "duplicate"

    if changed:
        _commit_cadence(db)
    else:
        db.rollback()
    return "invalid"


def _submit_today_feedback_response(
    db: Session,
    user_id: str,
) -> tuple[Literal["accepted", "duplicate", "invalid"], bool]:
    """Accept one answer for a claimed or recently rendered Decision Check."""
    config = _locked_user_config(db, user_id, create=False)
    if config is None:
        db.rollback()
        return "invalid", False

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    claimed_at = config.today_decision_check_claimed_at
    recent_claim = (
        claimed_at is not None
        and now - claimed_at < _TODAY_FEEDBACK_RESPONSE_TTL
    )
    shown_at = config.today_decision_check_shown_at
    recent_render = (
        shown_at is not None
        and now - shown_at < _TODAY_FEEDBACK_RESPONSE_TTL
    )
    if not recent_claim and not recent_render:
        if claimed_at is not None:
            config.today_decision_check_claimed_at = None
            _commit_cadence(db)
        else:
            db.rollback()
        return "invalid", False

    effective_shown_at = now if recent_claim else shown_at
    submitted_at = config.today_decision_check_submitted_at
    if (
        submitted_at is not None
        and effective_shown_at is not None
        and submitted_at >= effective_shown_at
    ):
        db.rollback()
        return "duplicate", False

    if claimed_at is not None:
        config.today_decision_check_claimed_at = None
    if recent_claim:
        config.today_decision_check_shown_at = now
    config.today_decision_check_submitted_at = now
    _commit_cadence(db)
    return "accepted", recent_claim


def _enforce_event_rate_limit(user_id: str) -> None:
    """Apply the shared product-event request budget."""
    allowed, retry_after = _EVENT_RATE_LIMIT.check_and_record(user_id)
    if not allowed:
        raise HTTPException(
            429,
            detail="PRODUCT_EVENT_RATE_LIMITED",
            headers={"Retry-After": str(retry_after)},
        )


@router.post("/product-events/today-feedback-claim")
def claim_today_feedback_prompt(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    """Reserve the Decision Check while the client renders it."""
    _enforce_event_rate_limit(user_id)
    claimed = _claim_today_feedback_prompt(db, user_id)
    return {"accepted": True, "duplicate": not claimed}


@router.post("/product-events")
def submit_product_event(
    body: ProductEventRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    """Validate and emit a privacy-safe product event."""
    _enforce_event_rate_limit(user_id)

    backfilled_shown = False
    if body.event_name == "today_feedback_shown":
        confirmation = _confirm_today_feedback_prompt(db, user_id)
        if confirmation == "invalid":
            raise HTTPException(409, detail="PRODUCT_EVENT_PROMPT_NOT_CLAIMED")
        if confirmation == "duplicate":
            return {"accepted": True, "duplicate": True}
    elif body.event_name == "today_feedback_submitted":
        submission, backfilled_shown = _submit_today_feedback_response(db, user_id)
        if submission == "invalid":
            raise HTTPException(409, detail="PRODUCT_EVENT_PROMPT_NOT_RENDERED")
        if submission == "duplicate":
            return {"accepted": True, "duplicate": True}
    else:
        dedup_key = f"{user_id}:{body.event_name}:{body.surface}"
        is_new, _ = _EVENT_DEDUP.check_and_record(dedup_key)
        if not is_new:
            return {"accepted": True, "duplicate": True}

    if backfilled_shown:
        telemetry.record_product_event(
            event_name="today_feedback_shown",
            surface=body.surface,
            app_version=body.app_version,
            response=None,
            user_id=user_id,
        )

    telemetry.record_product_event(
        event_name=body.event_name,
        surface=body.surface,
        app_version=body.app_version,
        response=body.response,
        user_id=user_id,
    )
    return {"accepted": True, "duplicate": False}
