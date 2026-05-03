"""Private-alpha waitlist signup.

Captures prospective users while Praxys is invitation-only. Stored locally
so the lead survives even if the support inbox is busy; an admin can pair
captured rows with manually-issued invitation codes from the Admin page.

The endpoint sits under /api/auth/* so it inherits the per-IP rate limit
in api/auth_rate_limit.py — the same defense that protects /register from
brute-force enumeration applies here.
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from db.models import WaitlistSignup
from db.session import get_db

logger = logging.getLogger(__name__)

waitlist_router = APIRouter()


class WaitlistRequest(BaseModel):
    email: EmailStr
    note: str = Field(default="", max_length=500)
    locale: str = Field(default="", max_length=10)


@waitlist_router.post("/waitlist")
def join_waitlist(body: WaitlistRequest, db: Session = Depends(get_db)) -> dict:
    """Record a waitlist signup. Idempotent on email — re-submitting the
    same address overwrites the prior note rather than stacking duplicates."""

    existing = (
        db.query(WaitlistSignup)
        .filter(WaitlistSignup.email == body.email)
        .first()
    )

    if existing:
        existing.note = body.note or existing.note
        existing.locale = body.locale or existing.locale
        existing.created_at = datetime.utcnow()
        db.commit()
        logger.info("waitlist signup refreshed: %s", body.email)
        return {"ok": True, "status": "refreshed"}

    try:
        signup = WaitlistSignup(
            email=body.email,
            note=body.note,
            locale=body.locale or None,
        )
        db.add(signup)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("waitlist signup failed for %s", body.email)
        raise HTTPException(500, detail="WAITLIST_SAVE_FAILED")

    logger.info("waitlist signup: %s", body.email)
    return {"ok": True, "status": "created"}
