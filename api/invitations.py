"""Shared invitation / admin-bypass primitives.

Registration rules (from CLAUDE.md):
1. Fresh DB (no users) → first register becomes admin, no invitation needed.
2. ADMIN_EMAIL (read via getenv_compat, i.e. PRAXYS_ADMIN_EMAIL or legacy
   TRAINSIGHT_ADMIN_EMAIL) match → no invitation needed, becomes admin.
3. All others → must provide a valid, unused invitation code.

These primitives exist so both the web-native registration route
(api/routes/register.py) and the WeChat registration path
(api/routes/wechat.py) apply the same rules without duplicating SQL.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import update
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
    """Look up an active, unused invitation by code. Returns None if not found.

    Note: this is a pre-check only. The authoritative "is this code free
    for me to claim?" answer comes from claim_invitation(), which performs
    the update atomically. A caller that relies on find_valid_invitation
    alone is racy — two concurrent registrations can both see the same
    unused invitation here and both proceed to create users.
    """
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


def claim_invitation(db: Session, code: str, user_id: str) -> bool:
    """Atomically claim an invitation for a user.

    Returns True if the claim succeeded (the invitation was active and
    unused, and is now marked used by this user). Returns False if no
    matching unused invitation exists — either the code is wrong, the
    invitation was deactivated, or a concurrent registration won the race.

    Callers MUST treat a False return as a hard failure: if a user was
    already created before calling this, that user should be rolled back
    or deleted, because they hold no valid invitation.

    Implementation: single UPDATE with a WHERE clause that also enforces
    the unused-ness check. SQLite 3.35+ (shipped 2021) guarantees this is
    atomic, so two concurrent transactions cannot both get rowcount=1.
    """
    stmt = (
        update(Invitation)
        .where(
            Invitation.code == code.strip().upper(),
            Invitation.is_active == True,  # noqa: E712
            Invitation.used_by.is_(None),
        )
        .values(
            used_by=user_id,
            used_at=datetime.now(timezone.utc),
        )
    )
    result = db.execute(stmt)
    db.commit()
    return result.rowcount == 1
