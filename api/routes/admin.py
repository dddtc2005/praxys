"""Admin endpoints — user management and invitation codes.

All endpoints require is_superuser=True on the authenticated user.
"""
import secrets
import string
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from api.auth import get_current_user_id
from db.session import get_db

router = APIRouter(prefix="/admin")


def _require_admin(user_id: str, db: Session) -> None:
    """Raise 403 if user is not a superuser."""
    from db.models import User
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_superuser:
        raise HTTPException(403, "Admin access required")


def _generate_code() -> str:
    """Generate a human-readable invitation code: TS-XXXX-XXXX."""
    chars = string.ascii_uppercase + string.digits
    part1 = ''.join(secrets.choice(chars) for _ in range(4))
    part2 = ''.join(secrets.choice(chars) for _ in range(4))
    return f"TS-{part1}-{part2}"


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
    """Generate a new one-time invitation code."""
    _require_admin(user_id, db)
    from db.models import Invitation

    code = _generate_code()
    # Ensure uniqueness (extremely unlikely collision)
    while db.query(Invitation).filter(Invitation.code == code).first():
        code = _generate_code()

    invitation = Invitation(
        code=code,
        created_by=user_id,
        note=body.note,
    )
    db.add(invitation)
    db.commit()
    return {"code": code, "note": body.note}


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
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
            "used_by": used_email,
            "used_at": inv.used_at.isoformat() if inv.used_at else None,
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
                "created_at": u.created_at.isoformat() if u.created_at else None,
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
    _require_admin(user_id, db)
    from db.models import User

    if target_user_id == user_id:
        raise HTTPException(400, "Cannot change your own role")

    user = db.query(User).filter(User.id == target_user_id).first()
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

    from db.models import (
        User, UserConfig, UserConnection, Activity, ActivitySplit,
        RecoveryData, FitnessData, TrainingPlan, Invitation,
    )

    user = db.query(User).filter(User.id == target_user_id).first()
    if not user:
        raise HTTPException(404, "User not found")

    email = user.email

    # Delete all user data (order matters for foreign keys)
    db.query(ActivitySplit).filter(ActivitySplit.user_id == target_user_id).delete()
    db.query(Activity).filter(Activity.user_id == target_user_id).delete()
    db.query(RecoveryData).filter(RecoveryData.user_id == target_user_id).delete()
    db.query(FitnessData).filter(FitnessData.user_id == target_user_id).delete()
    db.query(TrainingPlan).filter(TrainingPlan.user_id == target_user_id).delete()
    db.query(UserConnection).filter(UserConnection.user_id == target_user_id).delete()
    db.query(UserConfig).filter(UserConfig.user_id == target_user_id).delete()
    # Mark invitation as consumed (keep the record, don't reactivate)
    # Admin can generate a new code if needed
    db.query(Invitation).filter(Invitation.used_by == target_user_id).update(
        {"is_active": False}
    )
    from db.models import AiInsight
    db.query(AiInsight).filter(AiInsight.user_id == target_user_id).delete()
    db.delete(user)
    db.commit()

    return {"status": "deleted", "email": email}


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
        await async_session.commit()

    # Set demo flags (sync session)
    demo_user = db.query(User).filter(User.id == new_user.id).first()
    demo_user.is_demo = True
    demo_user.demo_of = user_id
    db.commit()

    return {
        "id": demo_user.id,
        "email": demo_user.email,
        "is_demo": True,
        "demo_of": user_id,
    }
