"""Account deletion helpers shared by self-service and admin routes."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from db.models import (
    Activity,
    ActivitySample,
    ActivitySplit,
    AiInsight,
    CacheRevision,
    DashboardCache,
    Feedback,
    FitnessData,
    Invitation,
    RecoveryData,
    TrainingPlan,
    User,
    UserConfig,
    UserConnection,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccountDeletionResult:
    """Summary returned after a committed account deletion."""

    email: str
    deleted_user_ids: list[str]


def _delete_user_owned_rows(db: Session, user_id: str) -> None:
    """Delete rows that directly belong to a user, excluding the user row."""
    for model in (
        ActivitySample,
        ActivitySplit,
        Activity,
        RecoveryData,
        FitnessData,
        TrainingPlan,
        UserConnection,
        UserConfig,
        AiInsight,
        CacheRevision,
        DashboardCache,
        Feedback,
    ):
        db.query(model).filter(model.user_id == user_id).delete(synchronize_session=False)

    db.query(Invitation).filter(
        or_(Invitation.used_by == user_id, Invitation.created_by == user_id)
    ).delete(synchronize_session=False)


def _clear_tokenstore(user_id: str) -> None:
    """Best-effort removal of on-disk Garmin OAuth tokens for a deleted user."""
    from api.routes.sync import clear_garmin_tokens

    try:
        clear_garmin_tokens(user_id)
    except OSError:
        logger.exception(
            "User %s deleted but Garmin tokenstore cleanup failed; orphan directory left on disk.",
            user_id,
        )


def delete_user_account(
    db: Session,
    user_id: str,
    *,
    enforce_last_admin_guard: bool = True,
) -> AccountDeletionResult:
    """Hard-delete a user account plus all directly owned rows.

    The operation commits before touching disk tokenstores so a filesystem
    cleanup issue cannot roll back the database deletion. A last-admin guard is
    enforced for self-service deletion and kept enabled for admin deletion as a
    defense-in-depth check.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "USER_NOT_FOUND")

    if enforce_last_admin_guard and user.is_superuser:
        admin_count = db.query(User).filter(User.is_superuser == True).count()  # noqa: E712
        if admin_count <= 1:
            raise HTTPException(400, "LAST_ADMIN_CANNOT_DELETE_ACCOUNT")

    email = user.email
    deleted_user_ids: list[str] = []

    demo_users = db.query(User).filter(User.demo_of == user_id).all()
    for demo_user in demo_users:
        _delete_user_owned_rows(db, demo_user.id)
        db.delete(demo_user)
        deleted_user_ids.append(demo_user.id)

    _delete_user_owned_rows(db, user_id)
    db.delete(user)
    deleted_user_ids.append(user_id)

    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Account deletion failed for user %s", user_id)
        raise HTTPException(500, "ACCOUNT_DELETE_FAILED")

    for deleted_user_id in deleted_user_ids:
        _clear_tokenstore(deleted_user_id)

    return AccountDeletionResult(email=email, deleted_user_ids=deleted_user_ids)
