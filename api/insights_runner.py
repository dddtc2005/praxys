"""Post-sync LLM insight generation runner.

Called after a sync finishes. Runs three insight generators (daily_brief,
training_review, race_forecast), each gated by:

- A *content-addressable* dataset hash: skip if the inputs that drive the
  insight haven't materially changed since the last generation.
- A *per-user daily cap*: skip remaining types if the cap is exhausted.

When the LLM is unavailable (Azure endpoint unset, SDK missing) the
generators return ``None`` and the rule-based prose elsewhere in the app
serves as the fallback. Sync never fails because of this hook — call sites
always wrap it in try/except.

Transaction ownership: the runner opens its own ``SessionLocal`` so its
commits / rollbacks are fully isolated from the caller's sync session.
The caller's ``db`` parameter is unused for writes — it's accepted so the
two call sites (sync route, scheduler) stay symmetric and so a future
refactor can plumb caller state without changing the signature again.
Tests inject ``_session=...`` to substitute an in-memory session.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from api.insight_feedback import (
    GENERATION_PROVENANCE_KEY,
    build_generation_provenance,
    merge_feedback_meta,
)

logger = logging.getLogger(__name__)


GENERATORS_ORDER = ("daily_brief", "training_review", "race_forecast")
_RUN_LOCKS = tuple(threading.Lock() for _ in range(64))


def run_insights_for_user(
    user_id: str, db: Session, counts: dict, *, _session: Optional[Session] = None
) -> dict:
    """Run all three insight generators for ``user_id``.

    Args:
        user_id: User the sync just completed for.
        db: Caller's session — used only as a "DB is ready" hint. The runner
            opens its own session for its work so its commits don't entangle
            with the sync transaction.
        counts: Per-platform row-count dict from the sync writer
            (e.g. ``{"activities": 5, "splits": 23}``). When all values
            are zero we know the sync was a no-op and skip generation.
        _session: Test-only override. Pass an in-memory session and the
            runner uses it directly instead of opening ``SessionLocal``.

    Returns:
        Per-insight-type status dict — one of: ``generated``, ``hash_match``,
        ``cap_reached``, ``generator_returned_none``, or ``superseded``. A
        top-level ``skipped`` key short-circuits the whole run.
    """
    if not _has_new_rows(counts):
        return {"skipped": "no_new_rows"}

    if _session is not None:
        return _run_serialized(_session, user_id)

    from db.session import SessionLocal

    own_session = SessionLocal()
    try:
        return _run_serialized(own_session, user_id)
    finally:
        own_session.close()


def _generation_lock_key(user_id: str) -> int:
    """Return a stable transaction-lock key for one user's LLM generation."""
    digest = hashlib.blake2b(
        f"insight-generation:{user_id}".encode("utf-8"),
        digest_size=8,
    ).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


def _lock_generation(db: Session, user_id: str) -> None:
    """Serialize insight generation within the current PostgreSQL transaction."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": _generation_lock_key(user_id)},
        )


def _run_serialized(db: Session, user_id: str) -> dict:
    """Serialize one user's runners before taking the source snapshot."""
    lock = _RUN_LOCKS[hash(user_id) % len(_RUN_LOCKS)]
    with lock:
        _lock_generation(db, user_id)
        try:
            return _run(db, user_id)
        finally:
            # Early-return paths do not commit, so roll back their read
            # transaction to release the transaction-scoped advisory lock.
            if db.in_transaction():
                db.rollback()


def _run(db: Session, user_id: str) -> dict:
    cap = _daily_cap()
    used_today = _count_today(user_id, db)
    if used_today >= cap:
        return {"skipped": "cap_reached"}

    # Imports deferred so this module is cheap to import (the post-sync hook
    # imports it on every sync, including ones with no new rows).
    from analysis.config import load_config_from_db
    from analysis.insight_hash import compute_dataset_hash
    from api.ai import build_training_context
    from api.insights_generator import (
        generate_daily_brief,
        generate_race_forecast,
        generate_training_review,
    )
    from db.models import AiInsight

    generators = {
        "daily_brief": generate_daily_brief,
        "training_review": generate_training_review,
        "race_forecast": generate_race_forecast,
    }

    # Build only against a stable revision vector. A sync that commits while
    # the context is loading invalidates the first attempt; one retry gives the
    # runner a coherent source snapshot without blocking sync writes.
    from db.cache_revision import SCOPES, get_revisions

    try:
        for _attempt in range(2):
            revisions_before = get_revisions(db, user_id, SCOPES)
            cfg = load_config_from_db(user_id, db)
            pillars = dict(getattr(cfg, "science", {}) or {})
            context = build_training_context(user_id=user_id, db=db)
            source_revisions = get_revisions(db, user_id, SCOPES)
            if revisions_before == source_revisions:
                break
            db.expire_all()
        else:
            logger.warning("Insight context changed repeatedly for user=%s", user_id)
            return {"skipped": "context_changed"}
    except Exception:
        logger.exception("Insight context build failed for user=%s", user_id)
        return {"skipped": "context_build_failed"}

    run_started_at = datetime.utcnow()

    from api import telemetry

    results: dict[str, str] = {}
    pending: list[tuple[str, dict, str]] = []
    for itype in GENERATORS_ORDER:
        new_hash = compute_dataset_hash(context, itype, science_pillars=pillars)
        existing = (
            db.query(AiInsight)
            .filter(AiInsight.user_id == user_id, AiInsight.insight_type == itype)
            .first()
        )
        if existing is not None and (existing.meta or {}).get("dataset_hash") == new_hash:
            results[itype] = "hash_match"

            continue
        if used_today + len(pending) >= cap:
            results[itype] = "cap_reached"

            continue
        payload = generators[itype](context, pillars)
        if payload is None:
            results[itype] = "generator_returned_none"

            continue
        pending.append((itype, payload, new_hash))

    # No database row locks are held during the LLM calls above. Serialize the
    # short write batch before its active-user and revision checks. PostgreSQL
    # uses the revision advisory lock inside _upsert_insight; SQLite needs an
    # explicit writer transaction so deletion cannot interleave before commit.
    if pending:
        from db.session import begin_serialized_write

        begin_serialized_write(db)
    for itype, payload, new_hash in pending:
        if not _upsert_insight(
            db,
            user_id,
            itype,
            payload,
            new_hash,
            source_revisions,
            run_started_at,
        ):
            results[itype] = "superseded"

            continue
        used_today += 1
        results[itype] = "generated"

    db.commit()
    for itype in GENERATORS_ORDER:
        status = results.get(itype)
        if status is not None:
            telemetry.record_coach_run(
                insight_type=itype,
                status=status,
                user_id=user_id,
            )
    return results


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _has_new_rows(counts: dict) -> bool:
    """Return True if any value in ``counts`` is a positive integer."""
    return any(isinstance(v, int) and v > 0 for v in (counts or {}).values())


def _daily_cap() -> int:
    try:
        return int(os.environ.get("PRAXYS_INSIGHT_DAILY_CAP", "30"))
    except ValueError:
        return 30


def _count_today(user_id: str, db: Session) -> int:
    """Count AiInsight rows generated for this user since UTC midnight.

    Uses naive UTC datetimes to match ``AiInsight.generated_at``'s
    ``datetime.utcnow`` default.
    """
    from db.models import AiInsight

    today_midnight = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.query(AiInsight)
        .filter(AiInsight.user_id == user_id, AiInsight.generated_at >= today_midnight)
        .count()
    )


def _insight_lock_key(user_id: str, insight_type: str) -> int:
    """Return a stable signed 64-bit key for a PostgreSQL advisory lock."""
    digest = hashlib.blake2b(
        f"{user_id}:{insight_type}".encode("utf-8"),
        digest_size=8,
    ).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


def _lock_insight_version(db: Session, user_id: str, insight_type: str) -> None:
    """Serialize cross-process PostgreSQL upserts for one insight slot."""
    if db.get_bind().dialect.name != "postgresql":
        return
    db.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _insight_lock_key(user_id, insight_type)},
    )


def _generation_started_at(meta: object) -> datetime | None:
    """Read the source snapshot timestamp from trusted runner provenance."""
    if not isinstance(meta, dict):
        return None
    provenance = meta.get(GENERATION_PROVENANCE_KEY)
    if not isinstance(provenance, dict):
        return None
    value = provenance.get("run_started_at")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None

def _upsert_insight(
    db: Session,
    user_id: str,
    itype: str,
    payload: dict,
    dataset_hash: str,
    source_revisions: dict[str, int],
    run_started_at: datetime,
) -> bool:
    """Upsert unless a later-started runner already published this slot."""
    from db.models import AiInsight, User

    _lock_insight_version(db, user_id, itype)
    from db.cache_revision import get_revisions, lock_revision_writes

    # Sync writers acquire this revision lock before flushing rows whose
    # foreign keys touch User. Keep the same order here to avoid a
    # revision-lock ↔ User-row deadlock on PostgreSQL.
    lock_revision_writes(db, user_id)
    current_revisions = get_revisions(db, user_id, source_revisions.keys())
    if current_revisions != source_revisions:
        return False

    user = (
        db.query(User)
        .populate_existing()
        .with_for_update()
        .filter(User.id == user_id)
        .first()
    )
    if user is None or not user.is_active:
        return False

    row = (
        db.query(AiInsight)
        .populate_existing()
        .with_for_update()
        .filter(AiInsight.user_id == user_id, AiInsight.insight_type == itype)
        .first()
    )
    existing_started_at = _generation_started_at(row.meta) if row is not None else None
    if existing_started_at is not None:
        if existing_started_at > run_started_at:
            return False
    elif (
        row is not None
        and row.generated_at is not None
        and row.generated_at > run_started_at
    ):
        return False
    if row is None:
        row = AiInsight(user_id=user_id, insight_type=itype)
        db.add(row)
    row.headline = payload["headline"]
    row.summary = payload["summary"]
    row.findings = payload["findings"]
    row.recommendations = payload["recommendations"]
    row.translations = payload.get("translations") or {}
    meta_extra = payload.get("meta_extra") or {}
    provenance = build_generation_provenance(
        meta_extra.get("model"),
        meta_extra.get("pillars"),
        run_started_at=run_started_at.isoformat(),
        source_revisions=source_revisions,
    )
    row.meta = merge_feedback_meta(
        db,
        user_id,
        itype,
        {
            **meta_extra,
            "dataset_hash": dataset_hash,
            GENERATION_PROVENANCE_KEY: provenance,
        },
        row.meta,
    )
    row.generated_at = datetime.utcnow()
    return True
