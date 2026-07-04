"""System-wide operational config (the AppConfig key-value table).

Praxys stores operator-owned runtime flags here — toggled from the Admin page,
not via env vars — so an admin can open/close self-registration and set the
seat cap without a redeploy. This module owns the *typed* accessors and the
safe defaults, so a fresh DB (no rows) behaves exactly like a configured one.

Security note: the self-registration gate is enforced SERVER-SIDE. The register
route (api/routes/register.py) calls :func:`is_registration_open` inside the
same transaction that creates the user; the Admin UI toggle and the public
``/api/public/config`` boolean are mirrors, never the enforcement point.

"Active users" for the cap = total registered non-demo accounts (a seat count),
per the product decision. The DAU/WAU numbers from :func:`activity_counts` are a
separate readiness *gauge* for the admin — they do NOT gate registration.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from api.invitations import count_outstanding_invitations
from db.models import AppConfig, User

# --- Keys + safe defaults --------------------------------------------------

KEY_REGISTRATION_OPEN = "registration_open"
KEY_REGISTRATION_MAX_USERS = "registration_max_users"

# Default CLOSED: opening self-registration must be a deliberate admin action.
DEFAULT_REGISTRATION_OPEN = False
# First scale target from the product plan (100 -> review -> 1000). A cap of 0
# would be surprising, so we default to the first milestone.
DEFAULT_MAX_USERS = 100

_TRUE = {"1", "true", "yes", "on"}


# --- Raw get/set -----------------------------------------------------------

def _get_raw(db: Session, key: str) -> str | None:
    row = db.query(AppConfig).filter(AppConfig.key == key).first()
    return row.value if row else None


def set_value(db: Session, key: str, value: str, updated_by: str | None = None) -> None:
    """Upsert a config value (stored as a string). Commits."""
    row = db.query(AppConfig).filter(AppConfig.key == key).first()
    if row is None:
        row = AppConfig(key=key, value=value, updated_by=updated_by)
        db.add(row)
    else:
        row.value = value
        row.updated_by = updated_by
        row.updated_at = datetime.utcnow()
    db.commit()


def get_bool(db: Session, key: str, default: bool) -> bool:
    raw = _get_raw(db, key)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE


def get_int(db: Session, key: str, default: int) -> int:
    raw = _get_raw(db, key)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


# --- Registration gate -----------------------------------------------------

def registration_flag_enabled(db: Session) -> bool:
    """The admin's raw open/closed toggle (ignores the seat cap)."""
    return get_bool(db, KEY_REGISTRATION_OPEN, DEFAULT_REGISTRATION_OPEN)


def registration_max_users(db: Session) -> int:
    """Seat cap: self-registration auto-closes at/above this many non-demo users."""
    return get_int(db, KEY_REGISTRATION_MAX_USERS, DEFAULT_MAX_USERS)


def count_registered_users(db: Session) -> int:
    """Seat count = registered non-demo accounts.

    Demo/mirror accounts (``is_demo``) don't consume a real seat, so they are
    excluded from the cap.
    """
    return (
        db.query(func.count(User.id))
        .filter(User.is_demo == False)  # noqa: E712
        .scalar()
        or 0
    )


def count_committed_seats(db: Session) -> int:
    """Seats already committed = registered non-demo users + outstanding codes.

    An outstanding invitation (active, unused, unexpired) reserves a seat, so
    the cap counts it too. This prevents overshoot: sending an invitation
    consumes a seat immediately, and redeeming it is net-zero (outstanding -1,
    registered +1). Consequently an invited user is never blocked by the cap —
    their seat was reserved when the code was issued.
    """
    return count_registered_users(db) + count_outstanding_invitations(db)


def is_registration_open(db: Session) -> tuple[bool, str]:
    """Effective self-registration state = flag ON *and* under the seat cap.

    The cap is measured in COMMITTED seats (registered users + outstanding
    invitation codes), not just actual registrations — see
    :func:`count_committed_seats`. Returns ``(open, reason)`` where reason is
    one of ``open`` / ``closed_flag`` / ``cap_reached`` for logging + telemetry.
    This is the single source of truth the register route consults for the
    code-less path. Invited users bypass this gate entirely.
    """
    if not registration_flag_enabled(db):
        return False, "closed_flag"
    if count_committed_seats(db) >= registration_max_users(db):
        return False, "cap_reached"
    return True, "open"


def registration_status(db: Session) -> dict:
    """Admin-facing snapshot of the gate (counts included — admin only)."""
    flag = registration_flag_enabled(db)
    cap = registration_max_users(db)
    registered = count_registered_users(db)
    outstanding = count_outstanding_invitations(db)
    committed = registered + outstanding
    open_effective = flag and committed < cap
    return {
        "registration_open": open_effective,
        "flag_enabled": flag,
        "max_users": cap,
        "registered_users": registered,
        "outstanding_invitations": outstanding,
        "committed_seats": committed,
        "remaining": max(cap - committed, 0),
        "cap_reached": committed >= cap,
    }


# --- Activity gauge (DAU/WAU) ----------------------------------------------

def activity_counts(db: Session) -> dict:
    """DAU/WAU readiness gauge from User.last_seen_at (admin only).

    Purely informational — helps the operator decide whether to raise the cap.
    Does NOT gate registration. Counts non-demo users seen within the window.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    def _seen_since(since: datetime) -> int:
        return (
            db.query(func.count(User.id))
            .filter(User.is_demo == False)  # noqa: E712
            .filter(User.last_seen_at.isnot(None))
            .filter(User.last_seen_at >= since)
            .scalar()
            or 0
        )

    return {
        "dau": _seen_since(day_ago),
        "wau": _seen_since(week_ago),
        "mau": _seen_since(month_ago),
        "total_users": count_registered_users(db),
    }