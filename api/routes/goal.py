"""Race / CP goal endpoint."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from api.auth import get_data_user_id
from api.dashboard_cache import cached_or_compute
from api.etag import ETagGuard, etag_guard_for_endpoint
from api.packs import RequestContext, get_race_pack
from db.session import get_db

router = APIRouter()


def _build_goal_payload(user_id: str, db: Session) -> dict:
    """Compute the /api/goal response from L1 packs (cache miss path)."""
    ctx = RequestContext(user_id=user_id, db=db)
    race = get_race_pack(ctx)
    return {
        "race_countdown": race["race_countdown"],
        "cp_trend": race["cp_trend"],
        "cp_trend_data": race["cp_trend_data"],
        "latest_cp": race["latest_cp"],
        "training_base": ctx.config.training_base,
        "display": ctx.display,
        "data_meta": ctx.data_meta,
        "science_notes": ctx.science_notes,
    }


@router.get("/goal")
def get_goal(
    response: Response,
    guard: ETagGuard = Depends(etag_guard_for_endpoint("goal")),
    user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
):
    if guard.is_match:
        return guard.not_modified()
    guard.apply(response)
    return cached_or_compute(
        db, user_id, "goal",
        compute=lambda: _build_goal_payload(user_id, db),
    )
