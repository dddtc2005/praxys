"""Authentication middleware — JWT token validation.

Every request to a protected endpoint must include a valid Bearer token
from the Authorization header. Tokens are issued by the /api/auth/login endpoint.
"""
import os
import logging

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from db.session import get_db

logger = logging.getLogger(__name__)

JWT_SECRET = os.environ.get("TRAINSIGHT_JWT_SECRET", "dev-secret-change-in-production!!")


def get_current_user_id(request: Request, db: Session = Depends(get_db)) -> str:
    """Get current user ID from JWT token in the Authorization header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Not authenticated")

    token = auth_header.split(" ", 1)[1]

    import jwt
    try:
        payload = jwt.decode(
            token, JWT_SECRET, algorithms=["HS256"],
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
    if user and user.is_demo and user.demo_of:
        return user.demo_of
    return user_id


def require_write_access(request: Request, db: Session = Depends(get_db)) -> str:
    """Get current user_id and verify write access.

    Raises 403 for demo accounts. Use this on WRITE endpoints.
    """
    user_id = get_current_user_id(request, db)
    from db.models import User
    user = db.query(User).filter(User.id == user_id).first()
    if user and user.is_demo:
        raise HTTPException(403, "Demo accounts cannot modify data")
    return user_id
