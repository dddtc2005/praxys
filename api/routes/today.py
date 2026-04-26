"""Today's training signal endpoint."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from api.auth import get_data_user_id
from api.dashboard_cache import cached_or_compute
from api.etag import ETagGuard, etag_guard_for_endpoint
from api.packs import (
    RequestContext,
    get_signal_pack,
    get_today_widgets,
)
from db.session import get_db

router = APIRouter()


def _recovery_theory_meta(science: dict) -> dict | None:
    """Extract recovery theory metadata for the Today page."""
    theory = science.get("recovery")
    if theory is None:
        return None
    return {
        "id": theory.id,
        "name": theory.name,
        "simple_description": theory.simple_description,
        "params": theory.params,
    }


def _build_today_payload(user_id: str, db: Session) -> dict:
    """Compute the /api/today response from L1 packs (cache miss path)."""
    ctx = RequestContext(user_id=user_id, db=db)
    signal = get_signal_pack(ctx)
    widgets = get_today_widgets(ctx)
    return {
        "signal": signal["signal"],
        "tsb_sparkline": signal["tsb_sparkline"],
        "warnings": signal["warnings"],
        "training_base": ctx.config.training_base,
        "display": ctx.display,
        "recovery_theory": _recovery_theory_meta(ctx.science),
        "recovery_analysis": signal["recovery_analysis"],
        "last_activity": widgets["last_activity"],
        "week_load": widgets["week_load"],
        "upcoming": widgets["upcoming"],
        "data_meta": ctx.data_meta,
        "science_notes": ctx.science_notes,
    }


@router.get("/today")
def get_today(
    response: Response,
    guard: ETagGuard = Depends(etag_guard_for_endpoint("today")),
    user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
):
    if guard.is_match:
        return guard.not_modified()
    guard.apply(response)
    return cached_or_compute(
        db, user_id, "today",
        compute=lambda: _build_today_payload(user_id, db),
    )
