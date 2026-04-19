"""FastAPI-Users configuration: user model, schemas, manager, auth backend.

Uses async SQLAlchemy sessions (aiosqlite) as required by FastAPI-Users v13+.
"""
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

from api.env_compat import getenv_compat

SECRET = getenv_compat("JWT_SECRET", "dev-secret-change-in-production!!")


class UserManager(BaseUserManager[User, str]):
    """Custom user manager for Praxys."""

    reset_password_token_secret = SECRET
    verification_token_secret = SECRET

    async def on_after_register(
        self, user: User, request: Optional[Request] = None
    ):
        """Hook called after a new user registers.

        Config creation is handled separately by the register route or
        the first request from the user.
        """
        pass


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
    return JWTStrategy(secret=SECRET, lifetime_seconds=lifetime)


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, str](get_user_manager, [auth_backend])

# Dependencies to get current user
current_active_user = fastapi_users.current_user(active=True)
current_optional_user = fastapi_users.current_user(active=True, optional=True)
