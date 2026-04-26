"""Race / CP goal endpoint."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth import get_data_user_id
from api.packs import RequestContext, get_race_pack
from db.session import get_db

router = APIRouter()


@router.get("/goal")
def get_goal(
    user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
):
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
