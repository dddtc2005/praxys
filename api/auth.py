"""Authentication middleware — JWT token validation.

Every request to a protected endpoint must include a valid Bearer token
from the Authorization header. Tokens are issued by the /api/auth/login endpoint.
"""
import logging
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from api.auth_secrets import get_jwt_secret
from db.session import get_db

logger = logging.getLogger(__name__)

# How stale User.last_seen_at must be before we rewrite it. Bounds the extra
# write to at most one UPDATE per user per window, keeping the WAU/DAU gauge
# (api/app_config.activity_counts) fed without a per-request DB write.
LAST_SEEN_THROTTLE = timedelta(minutes=15)


def _touch_last_seen(db: Session, user) -> None:
    """Best-effort, throttled update of the user's last-activity timestamp.

    Never raises: an activity-gauge write must not be able to fail a real
    request. Only writes when the stored value is missing or older than
    LAST_SEEN_THROTTLE.
    """
    try:
        now = datetime.utcnow()
        last = user.last_seen_at
        if last is None or (now - last) >= LAST_SEEN_THROTTLE:
            user.last_seen_at = now
            db.commit()
    except Exception:
        db.rollback()


def get_current_user_id(request: Request, db: Session = Depends(get_db)) -> str:
    """Get current user ID from JWT token in the Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")

    token = auth_header.split(" ", 1)[1]

    import jwt
    try:
        payload = jwt.decode(
            token, get_jwt_secret(), algorithms=["HS256"],
            audience=["fastapi-users:auth"],
        )
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(401, "Invalid token: no subject")

        # Verify user still exists and is active
        from db.models import User
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(401, "User not found")
        if not user.is_active:
            raise HTTPException(401, "User account is deactivated")

        _touch_last_seen(db, user)
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(401, f"Invalid token: {e}")


def get_data_user_id(request: Request, db: Session = Depends(get_db)) -> str:
    """Get the user_id whose data should be displayed.

    For demo users, returns the source admin's user_id (demo_of).
    For normal users, returns their own user_id.
    Use this on READ endpoints so demo users transparently see admin's data.
    """
    user_id = get_current_user_id(request, db)
    from db.models import User
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(401, "User not found")
    if user.is_demo and user.demo_of:
        # Verify the source admin still exists
        target = db.query(User).filter(User.id == user.demo_of, User.is_active == True).first()
        if not target:
            raise HTTPException(403, "Demo source account is no longer available")
        return user.demo_of
    return user_id


def require_write_access(request: Request, db: Session = Depends(get_db)) -> str:
    """Get current user_id and verify write access.

    Raises 403 for demo accounts. Fails closed — unknown users are rejected.
    Use this on WRITE endpoints.
    """
    user_id = get_current_user_id(request, db)
    from db.models import User
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(401, "User not found")
    if user.is_demo:
        raise HTTPException(403, "Demo accounts cannot modify data")
    return user_id
