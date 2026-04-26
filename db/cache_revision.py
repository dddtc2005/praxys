"""Per-(user, scope) cache-revision bookkeeping for HTTP ETag revalidation.

L2 (issue #147) — read-heavy / write-rare endpoints can return 304 Not
Modified when no relevant data has changed since the client's last visit.
The "relevant data" question is answered by these scope counters: each
endpoint pack reads a fixed set of tables, those tables are bucketed into
named scopes, and the ETag is a hash of the user's revision counter for
each scope the endpoint consumes.

Scope vocabulary (must stay in lockstep with ``api/etag.py::ENDPOINT_SCOPES``
and the bump points in ``db/sync_writer.py`` + the config-mutation routes):

    activities  — Activity rows (sync-written + AI insights)
    splits      — ActivitySplit rows
    recovery    — RecoveryData rows (Oura sleep/HRV/RHR + Garmin variants)
    fitness     — FitnessData rows (CP, LTHR, threshold pace, max/rest HR)
    plans       — TrainingPlan rows (Stryd push, AI plan upload/upsert/delete)
    config      — UserConfig rows (settings, science choice, goal updates)

A counter beats a timestamp because two writes within the same wall-clock
second still produce distinct revisions, so a 304 cannot accidentally hide
a fresh write that landed in the same second as the prior request.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.models import CacheRevision

logger = logging.getLogger(__name__)


# Allowed scope vocabulary. Used to fail fast on typos at bump time rather
# than silently writing a row that no ETag computation will ever read back.
SCOPES: tuple[str, ...] = (
    "activities",
    "splits",
    "recovery",
    "fitness",
    "plans",
    "config",
)


def bump_revisions(
    db: Session, user_id: str, scopes: Iterable[str],
) -> None:
    """Increment the revision counter for ``user_id`` × each scope.

    Inserts a row at revision 1 if none exists, otherwise atomically
    increments the existing row. Caller is responsible for committing the
    surrounding transaction; this function only stages the changes so it
    composes with the existing commit pattern in ``sync_writer.py`` and
    the route handlers (one ``db.commit()`` per request).

    Unknown scope names raise ``ValueError`` so a typo in a route handler
    surfaces in tests rather than silently producing 304s that never bust.
    """
    if not user_id or not scopes:
        return

    # De-duplicate while preserving order for stable test assertions.
    seen: set[str] = set()
    deduped: list[str] = []
    for s in scopes:
        if s in seen:
            continue
        if s not in SCOPES:
            raise ValueError(
                f"unknown cache scope {s!r}; expected one of {SCOPES}"
            )
        seen.add(s)
        deduped.append(s)

    now = datetime.utcnow()
    for scope in deduped:
        existing = db.execute(
            select(CacheRevision)
            .where(CacheRevision.user_id == user_id)
            .where(CacheRevision.scope == scope)
        ).scalar_one_or_none()

        if existing is None:
            try:
                db.add(CacheRevision(
                    user_id=user_id, scope=scope,
                    revision=1, bumped_at=now,
                ))
                db.flush()
            except IntegrityError:
                # Concurrent worker just inserted the row; fall through to
                # the increment branch on the now-existing record.
                db.rollback()
                existing = db.execute(
                    select(CacheRevision)
                    .where(CacheRevision.user_id == user_id)
                    .where(CacheRevision.scope == scope)
                ).scalar_one_or_none()
                if existing is not None:
                    existing.revision = (existing.revision or 0) + 1
                    existing.bumped_at = now
        else:
            existing.revision = (existing.revision or 0) + 1
            existing.bumped_at = now


def get_revisions(
    db: Session, user_id: str, scopes: Iterable[str],
) -> dict[str, int]:
    """Return ``{scope: revision}`` for the requested scopes.

    Missing rows are reported as revision 0 so the cold-start ETag is still
    deterministic and stable across the first read; the first write then
    flips that scope to 1, busting any cached response.
    """
    wanted = list(scopes)
    if not user_id or not wanted:
        return {}

    rows = db.execute(
        select(CacheRevision.scope, CacheRevision.revision)
        .where(CacheRevision.user_id == user_id)
        .where(CacheRevision.scope.in_(wanted))
    ).all()
    found = {scope: int(rev or 0) for scope, rev in rows}
    return {scope: found.get(scope, 0) for scope in wanted}
