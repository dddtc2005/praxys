"""Admin endpoints — user management and invitation codes.

All endpoints require is_superuser=True on the authenticated user.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from api import app_config, email_content, email_sender, invitations
from api.account_deletion import begin_active_admin_guard
from api.admin_ops import OpsSummaryResponse, OpsWindow, build_ops_summary
from api.auth import get_current_user_id
from api.views import utc_isoformat, require_admin as _require_admin
from db.session import get_db

router = APIRouter(prefix="/admin")

# Emailed invitation codes expire so a leaked/forwarded link cannot be redeemed
# indefinitely. Admin-generated codes (the /invitations button) stay non-expiring.
INVITE_EXPIRY_DAYS = 14


# ---------------------------------------------------------------------------
# Operations overview
# ---------------------------------------------------------------------------


@router.get("/ops/summary", response_model=OpsSummaryResponse)
def get_ops_summary(
    response: Response,
    window: OpsWindow = "24h",
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> OpsSummaryResponse:
    """Return the privacy-safe, aggregate-only admin operations snapshot."""
    _require_admin(user_id, db)
    # Live incidents and health probes must never be served from an intermediary
    # cache. Future Azure-backed subsections will own their short server-side TTL.
    response.headers["Cache-Control"] = "private, no-store"
    return build_ops_summary(db, window)


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


class RoleChangeRequest(BaseModel):
    is_superuser: bool


class CreateInvitationRequest(BaseModel):
    note: str = ""


@router.post("/invitations")
def create_invitation(
    body: CreateInvitationRequest = CreateInvitationRequest(),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Generate a new one-time invitation code (non-expiring)."""
    _require_admin(user_id, db)
    invitation = invitations.create_invitation(db, created_by=user_id, note=body.note)
    return {"code": invitation.code, "note": invitation.note}


@router.get("/invitations")
def list_invitations(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """List all invitation codes with usage status."""
    _require_admin(user_id, db)
    from db.models import Invitation, User

    invitations = db.query(Invitation).order_by(Invitation.created_at.desc()).all()
    result = []
    for inv in invitations:
        used_email = None
        if inv.used_by:
            used_user = db.query(User).filter(User.id == inv.used_by).first()
            used_email = used_user.email if used_user else None
        result.append({
            "id": inv.id,
            "code": inv.code,
            "note": inv.note,
            "is_active": inv.is_active,
            "created_at": utc_isoformat(inv.created_at),
            "used_by": used_email,
            "used_at": utc_isoformat(inv.used_at),
        })
    return {"invitations": result}


@router.delete("/invitations/{invitation_id}")
def revoke_invitation(
    invitation_id: int,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Revoke an invitation code (cannot be used after this)."""
    _require_admin(user_id, db)
    from db.models import Invitation

    inv = db.query(Invitation).filter(Invitation.id == invitation_id).first()
    if not inv:
        raise HTTPException(404, "Invitation not found")
    inv.is_active = False
    db.commit()
    return {"status": "revoked", "code": inv.code}


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------


@router.get("/users")
def list_users(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """List all registered users."""
    _require_admin(user_id, db)
    from db.models import User

    users = db.query(User).order_by(User.created_at).all()
    # Resolve demo_of emails for display
    user_emails = {u.id: u.email for u in users}
    return {
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "is_active": u.is_active,
                "is_superuser": u.is_superuser,
                "is_demo": u.is_demo,
                "demo_of": u.demo_of,
                "demo_of_email": user_emails.get(u.demo_of) if u.demo_of else None,
                "created_at": utc_isoformat(u.created_at),
            }
            for u in users
        ]
    }


@router.patch("/users/{target_user_id}/role")
def update_user_role(
    target_user_id: str,
    body: RoleChangeRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Toggle admin role for a user."""
    from db.models import User

    if target_user_id == user_id:
        raise HTTPException(400, "Cannot change your own role")

    if not body.is_superuser:
        begin_active_admin_guard(db)
    _require_admin(user_id, db, lock=not body.is_superuser)

    user = (
        db.query(User)
        .populate_existing()
        .with_for_update()
        .filter(User.id == target_user_id)
        .first()
    )
    if not user:
        raise HTTPException(404, "User not found")

    user.is_superuser = body.is_superuser
    db.commit()

    return {
        "id": user.id,
        "email": user.email,
        "is_superuser": user.is_superuser,
    }


@router.delete("/users/{target_user_id}")
def delete_user(
    target_user_id: str,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Delete a user and all their data. Cannot delete yourself."""
    _require_admin(user_id, db)
    if target_user_id == user_id:
        raise HTTPException(400, "Cannot delete yourself")

    from api.account_deletion import delete_user_account

    result = delete_user_account(db, target_user_id)
    return {"status": "deleted", "email": result.email}


# ---------------------------------------------------------------------------
# Demo accounts
# ---------------------------------------------------------------------------


class CreateDemoAccountRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/demo-accounts")
async def create_demo_account(
    body: CreateDemoAccountRequest,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Create a read-only demo account that mirrors the creating admin's data."""
    _require_admin(user_id, db)
    from db.models import User

    existing = db.query(User).filter(User.email == body.email).first()
    if existing:
        raise HTTPException(400, "Email already registered")

    # Create user via FastAPI-Users async path (handles password hashing)
    from db.session import AsyncSessionLocal
    from fastapi_users.db import SQLAlchemyUserDatabase
    from fastapi_users.schemas import BaseUserCreate
    from api.users import UserManager

    async with AsyncSessionLocal() as async_session:
        user_db = SQLAlchemyUserDatabase(async_session, User)
        user_manager = UserManager(user_db)
        user_create = BaseUserCreate(
            email=body.email,
            password=body.password,
            is_superuser=False,
            is_verified=True,
            is_active=True,
        )
        new_user = await user_manager.create(user_create)

        # Set demo flags in the same async session to avoid race condition
        from sqlalchemy import update
        await async_session.execute(
            update(User).where(User.id == new_user.id).values(
                is_demo=True, demo_of=user_id
            )
        )
        await async_session.commit()

    return {
        "id": new_user.id,
        "email": body.email,
        "is_demo": True,
        "demo_of": user_id,
    }


# ---------------------------------------------------------------------------
# Registration config (operational gate + seat cap) + activity gauge
# ---------------------------------------------------------------------------


class RegistrationConfigUpdate(BaseModel):
    # Both optional so the UI can PATCH either field independently.
    registration_open: bool | None = None
    registration_max_users: int | None = None


def _config_snapshot(db: Session) -> dict:
    """Full admin view: the gate + seat cap, the DAU/WAU gauge, email status."""
    return {
        "registration": app_config.registration_status(db),
        "activity": app_config.activity_counts(db),
        "email_configured": email_sender.is_available(),
    }


@router.get("/config")
def get_config(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Return the registration gate, seat cap, DAU/WAU gauge, and email status."""
    _require_admin(user_id, db)
    return _config_snapshot(db)


@router.patch("/config")
def update_config(
    body: RegistrationConfigUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Toggle self-registration and/or set the seat cap. Admin only.

    Enforcement of both lives server-side in the register route; this only
    persists the operator's intent into AppConfig.
    """
    _require_admin(user_id, db)
    if body.registration_open is not None:
        app_config.set_value(
            db,
            app_config.KEY_REGISTRATION_OPEN,
            "true" if body.registration_open else "false",
            updated_by=user_id,
        )
    if body.registration_max_users is not None:
        if body.registration_max_users < 0:
            raise HTTPException(400, "max_users must be >= 0")
        app_config.set_value(
            db,
            app_config.KEY_REGISTRATION_MAX_USERS,
            str(int(body.registration_max_users)),
            updated_by=user_id,
        )
    return _config_snapshot(db)


# ---------------------------------------------------------------------------
# Waitlist — list + invite (generate code, mark row, email it)
# ---------------------------------------------------------------------------


def _serialize_waitlist(row, code: str | None, registered: bool = False) -> dict:
    return {
        "id": row.id,
        "email": row.email,
        "note": row.note,
        "locale": row.locale,
        "created_at": utc_isoformat(row.created_at),
        "invited_at": utc_isoformat(row.invited_at),
        "invitation_id": row.invitation_id,
        "invitation_code": code,
        "registered": registered,
    }


@router.get("/waitlist")
def list_waitlist(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """List waitlist signups (newest first) with any issued invitation code."""
    _require_admin(user_id, db)
    from sqlalchemy import func

    from db.models import Invitation, User, WaitlistSignup

    rows = db.query(WaitlistSignup).order_by(WaitlistSignup.created_at.desc()).all()
    inv_ids = [r.invitation_id for r in rows if r.invitation_id]
    codes: dict[int, str] = {}
    if inv_ids:
        for inv in db.query(Invitation).filter(Invitation.id.in_(inv_ids)).all():
            codes[inv.id] = inv.code

    # A signup is "registered" once an account exists for its email (any
    # registration path - invited or open), compared case-insensitively. Lets
    # the admin UI stop offering "Re-invite" - which would mint a fresh code and
    # reserve another seat - for people who have already joined.
    emails = {(r.email or "").lower() for r in rows if r.email}
    registered: set[str] = set()
    if emails:
        for (uemail,) in (
            db.query(User.email).filter(func.lower(User.email).in_(emails)).all()
        ):
            if uemail:
                registered.add(uemail.lower())

    return {
        "signups": [
            _serialize_waitlist(
                r,
                codes.get(r.invitation_id) if r.invitation_id else None,
                (r.email or "").lower() in registered,
            )
            for r in rows
        ]
    }


@router.post("/waitlist/{signup_id}/invite")
def invite_waitlist_signup(
    signup_id: int,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Generate an invitation code for a waitlist signup and email it.

    Always generates + marks the row so the admin has a code to hand out even
    when SMTP is unconfigured or the send fails — the response carries the code
    and a ready-to-use invite URL for a copy / mailto fallback. Re-inviting a
    row first revokes its previous unused code.
    """
    _require_admin(user_id, db)
    from db.models import Invitation, WaitlistSignup

    signup = db.query(WaitlistSignup).filter(WaitlistSignup.id == signup_id).first()
    if not signup:
        raise HTTPException(404, "Waitlist signup not found")

    # Revoke a prior unused, active code on this row before issuing a new one,
    # so re-inviting does not leave orphaned live codes.
    if signup.invitation_id:
        old = db.query(Invitation).filter(Invitation.id == signup.invitation_id).first()
        if old and old.is_active and old.used_by is None:
            old.is_active = False
            db.commit()

    expires_at = datetime.utcnow() + timedelta(days=INVITE_EXPIRY_DAYS)
    invitation = invitations.create_invitation(
        db, created_by=user_id, note=f"waitlist:{signup.email}", expires_at=expires_at,
    )
    signup.invited_at = datetime.utcnow()
    signup.invitation_id = invitation.id
    db.commit()

    email_configured = email_sender.is_available()
    sent = False
    if email_configured:
        subject, text, html = email_content.invitation_email(
            invitation.code, expires_days=INVITE_EXPIRY_DAYS, locale=signup.locale,
        )
        sent = email_sender.send_email(signup.email, subject, text, html)

    return {
        "sent": sent,
        "email_configured": email_configured,
        "code": invitation.code,
        "email": signup.email,
        "invite_url": email_content.invite_url(invitation.code),
        "expires_at": utc_isoformat(expires_at),
    }
