"""Shared invitation / admin-bypass primitives.

Registration rules (from CLAUDE.md):
1. Fresh DB (no users) → first register becomes admin, no invitation needed.
2. ADMIN_EMAIL (read via getenv_compat, i.e. PRAXYS_ADMIN_EMAIL or legacy
   TRAINSIGHT_ADMIN_EMAIL) match → no invitation needed, becomes admin.
3. Open self-registration (admin toggles the gate on; see api/app_config.py)
   → no invitation needed, but the account must verify its email.
4. All others → must provide a valid, unused, unexpired invitation code.

These primitives exist so the web-native registration route
(api/routes/register.py), the WeChat registration path (api/routes/wechat.py),
and the waitlist-invite admin endpoint apply the same rules without
duplicating SQL.
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timezone

from sqlalchemy import func, or_, update
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


def generate_code() -> str:
    """Generate a human-readable invitation code: TS-XXXX-XXXX."""
    chars = string.ascii_uppercase + string.digits
    part1 = "".join(secrets.choice(chars) for _ in range(4))
    part2 = "".join(secrets.choice(chars) for _ in range(4))
    return f"TS-{part1}-{part2}"


def create_invitation(
    db: Session,
    created_by: str,
    note: str = "",
    expires_at: datetime | None = None,
) -> Invitation:
    """Create + persist a unique invitation code. Commits and returns the row.

    ``expires_at`` is optional (None = never expires, the admin-generated
    default). The waitlist-invite flow passes an expiry so emailed codes can't
    be claimed indefinitely.
    """
    code = generate_code()
    # Ensure uniqueness (extremely unlikely collision).
    while db.query(Invitation).filter(Invitation.code == code).first():
        code = generate_code()
    invitation = Invitation(
        code=code,
        created_by=created_by,
        note=note,
        expires_at=expires_at,
    )
    db.add(invitation)
    db.commit()
    return invitation


def _not_expired_clause():
    """SQLAlchemy clause: invitation has no expiry, or it is still in the future.

    Uses naive UTC (datetime.utcnow) to match how timestamps are stored
    elsewhere in the schema (Column defaults use datetime.utcnow).
    """
    now = datetime.utcnow()
    return or_(Invitation.expires_at.is_(None), Invitation.expires_at > now)


def count_outstanding_invitations(db: Session) -> int:
    """Count invitations that reserve a seat: active, unused, and unexpired.

    Used by the seat-cap accounting (api/app_config.count_committed_seats): a
    sent-but-unredeemed code reserves a seat so the cap can''t be overshot when
    outstanding invitations are later redeemed.
    """
    return (
        db.query(func.count(Invitation.id))
        .filter(
            Invitation.is_active == True,  # noqa: E712
            Invitation.used_by.is_(None),
            _not_expired_clause(),
        )
        .scalar()
        or 0
    )


def find_valid_invitation(db: Session, code: str | None) -> Invitation | None:
    """Look up an active, unused, unexpired invitation by code, or None.

    Note: this is a pre-check only. The authoritative "is this code free for me
    to claim?" answer comes from claim_invitation(), which performs the update
    atomically. A caller that relies on find_valid_invitation alone is racy —
    two concurrent registrations can both see the same unused invitation here.
    """
    if not code:
        return None
    return (
        db.query(Invitation)
        .filter(
            Invitation.code == code.strip().upper(),
            Invitation.is_active == True,  # noqa: E712 — SQLAlchemy boolean comparison
            Invitation.used_by.is_(None),
            _not_expired_clause(),
        )
        .first()
    )


def claim_invitation(db: Session, code: str, user_id: str) -> bool:
    """Atomically claim an invitation for a user.

    Returns True if the claim succeeded (the invitation was active, unused, and
    unexpired, and is now marked used by this user). Returns False if no
    matching invitation exists — wrong/expired/deactivated code, or a
    concurrent registration won the race.

    Callers MUST treat a False return as a hard failure: if a user was already
    created before calling this, that user should be rolled back or deleted,
    because they hold no valid invitation.

    Implementation: single UPDATE with a WHERE clause that also enforces the
    unused-ness AND not-expired checks. SQLite 3.35+ (shipped 2021) guarantees
    this is atomic, so two concurrent transactions cannot both get rowcount=1.
    """
    stmt = (
        update(Invitation)
        .where(
            Invitation.code == code.strip().upper(),
            Invitation.is_active == True,  # noqa: E712
            Invitation.used_by.is_(None),
            _not_expired_clause(),
        )
        .values(
            used_by=user_id,
            used_at=datetime.now(timezone.utc),
        )
    )
    result = db.execute(stmt)
    db.commit()
    return result.rowcount == 1