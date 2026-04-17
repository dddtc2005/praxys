"""Race / CP goal endpoint."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth import get_current_user_id
from api.deps import get_dashboard_data
from db.session import get_db

router = APIRouter()


@router.get("/goal")
def get_goal(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    data = get_dashboard_data(user_id=user_id, db=db)
    return {
        "race_countdown": data["race_countdown"],
        "cp_trend": data["cp_trend"],
        "cp_trend_data": data["cp_trend_data"],
        "latest_cp": data["latest_cp"],
        "training_base": data["training_base"],
        "display": data["display"],
        "data_meta": data.get("data_meta"),
        "science_notes": data.get("science_notes"),
    }
