"""FastAPI-Users configuration: user model, schemas, manager, auth backend.

Uses async SQLAlchemy sessions (aiosqlite) as required by FastAPI-Users v13+.
"""
import logging
import os
from typing import Optional

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, FastAPIUsers, schemas
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.session import get_async_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class UserRead(schemas.BaseUser[str]):
    """Public user representation."""

    pass


class UserCreate(schemas.BaseUserCreate):
    """User registration payload."""

    pass


class UserUpdate(schemas.BaseUserUpdate):
    """User update payload."""

    pass


# ---------------------------------------------------------------------------
# User Database Adapter (async)
# ---------------------------------------------------------------------------


async def get_user_db(session: AsyncSession = Depends(get_async_db)):
    """Yield a FastAPI-Users SQLAlchemy database adapter."""
    yield SQLAlchemyUserDatabase(session, User)


# ---------------------------------------------------------------------------
# User Manager
# ---------------------------------------------------------------------------

from api.auth_secrets import get_jwt_secret
from api.env_compat import getenv_compat


class UserManager(BaseUserManager[User, str]):
    """Custom user manager for Praxys."""

    def parse_id(self, value) -> str:
        """Parse the user id carried in reset/verify tokens.

        User.id is a String(36) holding ``str(uuid4())`` — a string, not a
        UUID object — so we must NOT use UUIDIDMixin (it returns a uuid.UUID
        that would not equal the stored string in a WHERE clause). We validate
        the value is a well-formed UUID (raising InvalidID otherwise, per the
        FastAPI-Users contract) and return its canonical string form, which
        matches how ids are stored. Without this, /api/auth/verify raises
        NotImplementedError from the base manager.
        """
        from uuid import UUID
        from fastapi_users import exceptions
        try:
            return str(UUID(str(value)))
        except (ValueError, AttributeError, TypeError) as e:
            raise exceptions.InvalidID() from e

    @property
    def reset_password_token_secret(self) -> str:
        return get_jwt_secret()

    @property
    def verification_token_secret(self) -> str:
        return get_jwt_secret()

    async def on_after_register(
        self, user: User, request: Optional[Request] = None
    ):
        """Hook called after a new user registers.

        Config creation is handled separately by the register route or
        the first request from the user.
        """
        pass

    async def on_after_request_verify(
        self, user: User, token: str, request: Optional[Request] = None
    ):
        """Send the email-ownership verification link.

        Triggered by the register route (open, code-less self-signups) and by
        the /request-verify-token endpoint (resend). The blocking SMTP send is
        pushed to a threadpool so it never stalls the event loop, and any
        failure is swallowed — the user can re-request. Never raises.
        """
        from starlette.concurrency import run_in_threadpool
        from api import email_content, email_sender

        if not email_sender.is_available():
            logger.warning(
                "verify requested but email not configured; user %s cannot "
                "receive a link", user.id,
            )
            return
        subject, text, html = email_content.verification_email(token)
        try:
            await run_in_threadpool(
                email_sender.send_email, user.email, subject, text, html
            )
        except Exception:
            logger.warning("verification email send raised", exc_info=False)

    async def on_after_verify(
        self, user: User, request: Optional[Request] = None
    ):
        """Log successful email verification (audit trail)."""
        logger.info("user %s verified email", user.id)


async def get_user_manager(user_db=Depends(get_user_db)):
    """Yield a UserManager instance."""
    yield UserManager(user_db)


# ---------------------------------------------------------------------------
# Auth Backend (JWT bearer tokens)
# ---------------------------------------------------------------------------

bearer_transport = BearerTransport(tokenUrl="/api/auth/login")


def get_jwt_strategy() -> JWTStrategy:
    """Create a JWT strategy with configurable lifetime."""
    lifetime = int(
        getenv_compat("JWT_LIFETIME_SECS", str(7 * 24 * 3600)) or str(7 * 24 * 3600)
    )
    return JWTStrategy(secret=get_jwt_secret(), lifetime_seconds=lifetime)


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, str](get_user_manager, [auth_backend])

# Dependencies to get current user
current_active_user = fastapi_users.current_user(active=True)
current_optional_user = fastapi_users.current_user(active=True, optional=True)
