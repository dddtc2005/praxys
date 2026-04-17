"""Custom registration endpoint with invitation code verification.

Registration rules:
1. Fresh DB (no users) → first register becomes admin, no invitation needed
2. TRAINSIGHT_ADMIN_EMAIL match → no invitation needed, becomes admin (optional safety net)
3. All other users → must provide a valid, unused invitation code
"""
import logging
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from db.session import get_db

logger = logging.getLogger(__name__)

register_router = APIRouter()

ADMIN_EMAIL = os.environ.get("TRAINSIGHT_ADMIN_EMAIL", "")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    invitation_code: str = ""


@register_router.post("/register")
async def register(
    body: RegisterRequest,
    db: Session = Depends(get_db),
) -> dict:
    """Register a new user.

    First user on a fresh DB becomes admin without an invitation code.
    Subsequent users must provide a valid invitation code.
    """
    from db.models import User, Invitation

    # Check if email already registered
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(400, detail="REGISTER_USER_ALREADY_EXISTS")

    # Admin email override (optional env var — always bypasses invitation, always admin)
    is_admin_email = bool(ADMIN_EMAIL) and body.email.lower() == ADMIN_EMAIL.lower()
    if is_admin_email:
        logger.info("Admin email override used for registration: %s", body.email)

    # Pre-check invitation for non-admin-email users (fast fail before async session).
    # The actual first-user check is done inside the async session to prevent race conditions.
    invitation = None
    if not is_admin_email and body.invitation_code:
        invitation = db.query(Invitation).filter(
            Invitation.code == body.invitation_code.strip().upper(),
            Invitation.is_active == True,
            Invitation.used_by == None,
        ).first()

    # Create user inside async session — first-user check is atomic here
    from db.models import User as UserModel
    from db.session import AsyncSessionLocal
    from fastapi_users.db import SQLAlchemyUserDatabase
    from fastapi_users.schemas import BaseUserCreate
    from api.users import UserManager

    async with AsyncSessionLocal() as async_session:
        # Atomic first-user check inside the same session that creates the user
        result = await async_session.execute(
            select(func.count()).select_from(UserModel)
        )
        user_count = result.scalar() or 0
        is_first_user = user_count == 0

        is_admin = bool(is_first_user or is_admin_email)

        # Require invitation if not first user and not admin email
        if not is_first_user and not is_admin_email:
            if not invitation:
                if not body.invitation_code:
                    raise HTTPException(400, detail="REGISTER_INVITATION_REQUIRED")
                raise HTTPException(400, detail="REGISTER_INVALID_INVITATION")

        user_db = SQLAlchemyUserDatabase(async_session, UserModel)
        user_manager = UserManager(user_db)

        user_create = BaseUserCreate(
            email=body.email,
            password=body.password,
            is_superuser=is_admin,
            is_verified=True,
            is_active=True,
        )

        try:
            user = await user_manager.create(user_create)
        except Exception as e:
            raise HTTPException(400, detail=str(e))

        await async_session.commit()

    # Mark invitation as used (sync session)
    if invitation:
        invitation.used_by = user.id
        invitation.used_at = datetime.utcnow()
        db.commit()

    return {
        "id": user.id,
        "email": user.email,
        "is_superuser": user.is_superuser,
    }
