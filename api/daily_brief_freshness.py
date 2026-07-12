"""Server-owned freshness metadata for ``daily_brief`` insights."""
from __future__ import annotations

from datetime import date
from typing import Any

from analysis.insight_hash import compute_dataset_hash
from api.insight_feedback import is_dataset_hash

DAILY_BRIEF_FRESHNESS_KEY = "daily_brief_freshness"


def build_daily_brief_freshness_meta(
    context: dict,
    science_pillars: dict[str, str] | None,
    *,
    for_date: date,
) -> dict[str, str]:
    """Build the server-owned freshness payload for a daily brief."""
    return {
        "for_date": for_date.isoformat(),
        "today_hash": compute_dataset_hash(
            context,
            "daily_brief",
            science_pillars=science_pillars,
        ),
    }


def compute_current_daily_brief_freshness(user_id: str, db: Any) -> dict[str, str]:
    """Compute the current daily-brief freshness state via the lightweight Today path.

    Returns a server-owned dict with:
    - ``for_date``: the server-local date the brief is valid for
    - ``today_hash``: the canonical daily-brief input hash for that date
    """
    from api.packs import RequestContext
    from api.deps import _get_todays_plan
    from analysis.metrics import daily_training_signal

    ctx = RequestContext(user_id=user_id, db=db)
    fitness_series = ctx.fitness_series
    current_tsb = (
        float(fitness_series["tsb"].iloc[-1])
        if not fitness_series["tsb"].empty
        else 0.0
    )
    planned_today, planned_detail = _get_todays_plan(ctx.plan, ctx.today)
    load_theory = ctx.science.get("load")
    signal = daily_training_signal(
        ctx.recovery_analysis,
        current_tsb,
        planned_today,
        planned_detail=planned_detail,
        signal_thresholds=load_theory.signal if load_theory else None,
        hrv_only=True,
    )
    daily_context = {
        "recovery_state": {
            "readiness": (signal.get("recovery") or {}).get("readiness"),
            "hrv_ms": (signal.get("recovery") or {}).get("hrv_ms"),
            "hrv_trend_pct": (signal.get("recovery") or {}).get("hrv_trend_pct"),
            "sleep_score": (signal.get("recovery") or {}).get("sleep_score"),
        },
        "current_fitness": {
            "ctl": (
                float(fitness_series["ctl"].iloc[-1])
                if not fitness_series["ctl"].empty
                else None
            ),
            "atl": (
                float(fitness_series["atl"].iloc[-1])
                if not fitness_series["atl"].empty
                else None
            ),
            "tsb": current_tsb,
        },
        "today_signal": {
            "recommendation": signal.get("recommendation"),
            "reason": signal.get("reason"),
            "alternatives": signal.get("alternatives") or [],
        },
        "planned_today": planned_detail,
    }
    return build_daily_brief_freshness_meta(
        daily_context,
        dict(getattr(ctx.config, "science", {}) or {}),
        for_date=ctx.today,
    )


def is_current_daily_brief_freshness(
    meta: object,
    current_freshness: dict[str, str] | None,
) -> bool:
    """Return whether stored freshness metadata matches the current Today state.

    Returns ``False`` for unverifiable rows (missing metadata, wrong types, or
    malformed hashes) as well as for definite freshness mismatches.
    """
    if current_freshness is None:
        return False
    if not isinstance(meta, dict):
        return False
    stored = meta.get(DAILY_BRIEF_FRESHNESS_KEY)
    if not isinstance(stored, dict):
        return False
    stored_for_date = stored.get("for_date")
    stored_today_hash = stored.get("today_hash")
    if not isinstance(stored_for_date, str):
        return False
    if not isinstance(stored_today_hash, str) or not is_dataset_hash(stored_today_hash):
        return False
    return (
        stored_for_date == current_freshness.get("for_date")
        and stored_today_hash == current_freshness.get("today_hash")
    )
