"""Custom registration endpoint with invitation code verification.

Registration rules live in api/invitations.py and are shared with the
WeChat registration route (api/routes/wechat.py).

Admin email (ADMIN_EMAIL env, via getenv_compat) bypasses invitation
checks — see api/invitations.py::is_admin_email.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.invitations import (
    claim_invitation,
    find_valid_invitation,
    is_admin_email,
)
from db.session import get_db

logger = logging.getLogger(__name__)

register_router = APIRouter()


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
    Subsequent users must provide a valid invitation code, unless their
    email matches ADMIN_EMAIL (see api/invitations.py).
    """
    from db.models import User

    # Check if email already registered
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(400, detail="REGISTER_USER_ALREADY_EXISTS")

    admin_email_bypass = is_admin_email(body.email)
    if admin_email_bypass:
        logger.info("Admin email override used for registration: %s", body.email)

    # Pre-check invitation for non-admin-email users (fast fail before async session).
    # The actual first-user check is done inside the async session to prevent race conditions.
    invitation = None
    if not admin_email_bypass and body.invitation_code:
        invitation = find_valid_invitation(db, body.invitation_code)

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

        is_admin = bool(is_first_user or admin_email_bypass)

        # Require invitation if not first user and not admin email
        if not is_first_user and not admin_email_bypass:
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
        except IntegrityError:
            # Race: another request just registered the same email.
            logger.exception("register integrity error for %s", body.email)
            raise HTTPException(409, detail="REGISTER_USER_ALREADY_EXISTS")
        except HTTPException:
            raise
        except Exception:
            # Any other failure is a server bug, not a user error. Log it
            # and surface an opaque 500 so we don't leak internals.
            logger.exception("register failed for %s", body.email)
            raise HTTPException(500, detail="REGISTER_CREATE_FAILED")

        await async_session.commit()

    # Atomically claim the invitation. If we lose the race to another
    # registration using the same code, delete the user we just created
    # so they can't sneak in without a valid claim.
    if invitation:
        claimed = claim_invitation(db, body.invitation_code, user.id)
        if not claimed:
            logger.warning(
                "invitation race lost after user creation — rolling back user %s",
                user.id,
            )
            # Use a fresh async session; the previous one is closed.
            async with AsyncSessionLocal() as cleanup_session:
                await cleanup_session.execute(
                    UserModel.__table__.delete().where(UserModel.id == user.id)
                )
                await cleanup_session.commit()
            raise HTTPException(400, detail="REGISTER_INVALID_INVITATION")

    return {
        "id": user.id,
        "email": user.email,
        "is_superuser": user.is_superuser,
    }
