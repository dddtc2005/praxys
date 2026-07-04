"""Custom registration endpoint with invitation code + open-gate handling.

Registration rules live in api/invitations.py and api/app_config.py and are
shared with the WeChat registration route (api/routes/wechat.py).

Paths:
  * first user (fresh DB) or ADMIN_EMAIL  -> admin, no code, auto-verified.
  * valid invitation code                 -> auto-verified (pre-trusted).
  * open self-registration (gate ON + under the seat cap + no code) -> created
    UNVERIFIED; an email-ownership link is sent and login is blocked until the
    user clicks it. Degrades to auto-verified only when SMTP is unconfigured
    (dev), with a loud warning.

Security notes:
  * The open/closed gate AND the seat cap are enforced server-side. The cap is
    re-checked inside the creating session as a best-effort backstop — it closes
    the gap between the sync pre-check and the create, but is NOT fully atomic
    (unlike claim_invitation): a handful of exactly-concurrent code-less signups
    can overshoot the cap by a few. That is acceptable because the cap is a soft
    operational readiness gate, not a security boundary — invited users bypass
    it, and open signups land unverified until they confirm their email. The
    Admin UI toggle and the public /api/public/config boolean are mirrors, never
    the enforcement point.
  * A hidden honeypot field rejects naive bots without creating anything.
  * Per-IP rate limiting (api/auth_rate_limit.py) still applies to this route.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api import app_config
from api.email_sender import is_available as email_available
from api.invitations import (
    claim_invitation,
    find_valid_invitation,
    is_admin_email,
)
from api.legal import TERMS_VERSION
from db.session import get_db

logger = logging.getLogger(__name__)

register_router = APIRouter()


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    invitation_code: str = ""
    accepted_terms: bool = False
    # Honeypot: a hidden field real users never see or fill. A non-empty value
    # is a strong bot signal — we reject without creating anything. Named to
    # look like a real field so naive autofill bots take the bait.
    website: str = ""


@register_router.post("/register")
async def register(
    body: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Register a new user (see module docstring for the path matrix)."""
    from db.models import User

    # Honeypot — reject bots before doing any work.
    if body.website.strip():
        logger.warning("register: honeypot tripped; rejecting as bot")
        raise HTTPException(400, detail="REGISTER_FAILED")

    # Email already registered?
    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(400, detail="REGISTER_USER_ALREADY_EXISTS")

    # EULA gate: every account must accept the Terms/EULA at registration.
    if not body.accepted_terms:
        raise HTTPException(400, detail="REGISTER_TERMS_NOT_ACCEPTED")

    admin_email_bypass = is_admin_email(body.email)
    if admin_email_bypass:
        logger.info("Admin email override used for registration: %s", body.email)

    # Pre-check invitation (fast fail). Expiry is enforced inside the query.
    invitation = None
    if not admin_email_bypass and body.invitation_code:
        invitation = find_valid_invitation(db, body.invitation_code)

    # Read the registration gate + cap once (sync session).
    reg_open, reg_reason = app_config.is_registration_open(db)
    max_users = app_config.registration_max_users(db)

    from db.models import User as UserModel
    from db.session import AsyncSessionLocal
    from fastapi_users.db import SQLAlchemyUserDatabase
    from fastapi_users.schemas import BaseUserCreate
    from api.users import UserManager

    async with AsyncSessionLocal() as async_session:
        # Atomic counts inside the creating session.
        total = (
            await async_session.execute(select(func.count()).select_from(UserModel))
        ).scalar() or 0
        is_first_user = total == 0
        non_demo = (
            await async_session.execute(
                select(func.count())
                .select_from(UserModel)
                .where(UserModel.is_demo == False)  # noqa: E712
            )
        ).scalar() or 0

        privileged = bool(is_first_user or admin_email_bypass)
        is_admin = privileged
        open_signup = False

        if privileged:
            pass  # no code needed, auto-verify
        elif invitation:
            pass  # valid code, auto-verify (pre-trusted)
        else:
            # No valid invitation. If a code was supplied it is invalid/expired
            # — say so rather than silently open-registering a mistyped code.
            if body.invitation_code:
                raise HTTPException(400, detail="REGISTER_INVALID_INVITATION")
            # Truly code-less: allowed only when the gate is open.
            if not reg_open:
                logger.info("register blocked: gate closed (%s)", reg_reason)
                raise HTTPException(403, detail="REGISTER_CLOSED")
            # Seat-cap backstop, re-checked inside the creating session. The cap
            # counts COMMITTED seats = registered non-demo users + outstanding
            # (active, unused, unexpired) invitation codes. This closes the
            # sync-precheck -> create gap, but is best-effort, NOT atomic like
            # claim_invitation(): under truly concurrent code-less signups the
            # committed total can overshoot by a few. Acceptable — a soft
            # readiness gate, not a security limit (see the module docstring).
            from db.models import Invitation as InvitationModel

            now = datetime.utcnow()
            outstanding = (
                await async_session.execute(
                    select(func.count())
                    .select_from(InvitationModel)
                    .where(
                        InvitationModel.is_active == True,  # noqa: E712
                        InvitationModel.used_by.is_(None),
                        or_(
                            InvitationModel.expires_at.is_(None),
                            InvitationModel.expires_at > now,
                        ),
                    )
                )
            ).scalar() or 0
            committed = non_demo + outstanding
            if committed >= max_users:
                logger.info(
                    "register blocked: cap reached (committed %s/%s)",
                    committed, max_users,
                )
                raise HTTPException(403, detail="REGISTER_CLOSED")
            open_signup = True

        # Verification: open signups are unverified UNLESS email is unconfigured.
        can_email = email_available()
        needs_verification = bool(open_signup and can_email)
        if open_signup and not can_email:
            logger.warning(
                "open self-registration for %s created VERIFIED because SMTP is "
                "not configured — no email-ownership check performed",
                body.email,
            )

        user_db = SQLAlchemyUserDatabase(async_session, UserModel)
        user_manager = UserManager(user_db)

        user_create = BaseUserCreate(
            email=body.email,
            password=body.password,
            is_superuser=is_admin,
            is_verified=not needs_verification,
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
            # Any other failure is a server bug, not a user error.
            logger.exception("register failed for %s", body.email)
            raise HTTPException(500, detail="REGISTER_CREATE_FAILED")

        # Record EULA acceptance on the persisted user.
        user.terms_version = TERMS_VERSION
        user.terms_accepted_at = datetime.now(timezone.utc)
        async_session.add(user)
        await async_session.commit()

        # Open path: send the verification email. request_verify() generates a
        # token and calls on_after_request_verify (api/users.py) to send it.
        if needs_verification:
            try:
                await user_manager.request_verify(user, request)
            except Exception:
                logger.warning(
                    "register: request_verify failed for new user %s", user.id
                )

    # Atomically claim the invitation (invited path only). If we lose the race
    # to another registration using the same code, delete the user we just
    # created so they can't sneak in without a valid claim.
    if invitation:
        claimed = claim_invitation(db, body.invitation_code, user.id)
        if not claimed:
            logger.warning(
                "invitation race lost after user creation — rolling back user %s",
                user.id,
            )
            async with AsyncSessionLocal() as cleanup_session:
                await cleanup_session.execute(
                    UserModel.__table__.delete().where(UserModel.id == user.id)
                )
                await cleanup_session.commit()
            raise HTTPException(400, detail="REGISTER_INVALID_INVITATION")

    # Open signups don't get a session — they must verify their email first.
    if needs_verification:
        return {"verification_required": True, "email": user.email}

    return {
        "id": user.id,
        "email": user.email,
        "is_superuser": user.is_superuser,
    }