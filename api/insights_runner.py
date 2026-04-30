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
The caller passes a session in only as a hint that DB infrastructure is
ready; tests inject their own session to bypass ``SessionLocal``.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional  # noqa: F401  (kept for explicit Optional[Session] signature)

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


GENERATORS_ORDER = ("daily_brief", "training_review", "race_forecast")


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
        ``cap_reached``, ``generator_returned_none``. A top-level ``skipped``
        key short-circuits the whole run.
    """
    if not _has_new_rows(counts):
        return {"skipped": "no_new_rows"}

    if _session is not None:
        return _run(_session, user_id)

    from db.session import SessionLocal

    own_session = SessionLocal()
    try:
        return _run(own_session, user_id)
    finally:
        own_session.close()


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

    # Building context can fail (corrupt row, missing science YAML, transient
    # DB blip). Catch internally so the runner's "I never break sync"
    # contract doesn't depend on caller hygiene.
    try:
        cfg = load_config_from_db(user_id, db)
        pillars = dict(getattr(cfg, "science", {}) or {})
        context = build_training_context(user_id=user_id, db=db)
    except Exception:
        logger.exception("Insight context build failed for user=%s", user_id)
        return {"skipped": "context_build_failed"}

    results: dict[str, str] = {}
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
        if used_today >= cap:
            results[itype] = "cap_reached"
            continue
        payload = generators[itype](context, pillars)
        if payload is None:
            results[itype] = "generator_returned_none"
            continue
        _upsert_insight(db, user_id, itype, payload, new_hash)
        used_today += 1
        results[itype] = "generated"

    db.commit()
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


def _upsert_insight(
    db: Session, user_id: str, itype: str, payload: dict, dataset_hash: str
) -> None:
    """Upsert an AiInsight row from a generator payload."""
    from db.models import AiInsight

    row = (
        db.query(AiInsight)
        .filter(AiInsight.user_id == user_id, AiInsight.insight_type == itype)
        .first()
    )
    if row is None:
        row = AiInsight(user_id=user_id, insight_type=itype)
        db.add(row)
    row.headline = payload["headline"]
    row.summary = payload["summary"]
    row.findings = payload["findings"]
    row.recommendations = payload["recommendations"]
    row.translations = payload.get("translations") or {}
    meta_extra = payload.get("meta_extra") or {}
    row.meta = {**(row.meta or {}), "dataset_hash": dataset_hash, **meta_extra}
    row.generated_at = datetime.utcnow()
