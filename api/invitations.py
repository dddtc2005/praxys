"""Shared invitation / admin-bypass primitives.

Registration rules (from CLAUDE.md):
1. Fresh DB (no users) → first register becomes admin, no invitation needed.
2. PRAXYS_ADMIN_EMAIL match → no invitation needed, becomes admin.
3. All others → must provide a valid, unused invitation code.

These primitives exist so both the web-native registration route
(api/routes/register.py) and the WeChat registration path
(api/routes/wechat.py) apply the same rules without duplicating SQL.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from api.env_compat import getenv_compat
from db.models import Invitation, User


def is_admin_email(email: str | None) -> bool:
    """True if email matches the configured admin override."""
    if not email:
        return False
    admin_email = getenv_compat("ADMIN_EMAIL", "") or ""
    return bool(admin_email) and email.lower() == admin_email.lower()


def count_users(db: Session) -> int:
    """Total number of registered users (for the first-user admin rule)."""
    return db.query(User).count()


def find_valid_invitation(db: Session, code: str | None) -> Invitation | None:
    """Look up an active, unused invitation by code. Returns None if not found."""
    if not code:
        return None
    return (
        db.query(Invitation)
        .filter(
            Invitation.code == code.strip().upper(),
            Invitation.is_active == True,  # noqa: E712 — SQLAlchemy boolean comparison
            Invitation.used_by.is_(None),
        )
        .first()
    )


def consume_invitation(db: Session, invitation: Invitation, user_id: str) -> None:
    """Mark an invitation as used by the given user. Commits the transaction."""
    invitation.used_by = user_id
    invitation.used_at = datetime.utcnow()
    db.commit()
