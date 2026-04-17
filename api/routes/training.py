"""Training analysis endpoint."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth import get_data_user_id
from api.deps import get_dashboard_data
from db.session import get_db

router = APIRouter()


@router.get("/training")
def get_training(
    user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
):
    data = get_dashboard_data(user_id=user_id, db=db)
    return {
        "diagnosis": data["diagnosis"],
        "fitness_fatigue": data["fitness_fatigue"],
        "cp_trend": data["cp_trend"],
        "weekly_review": data["weekly_review"],
        "workout_flags": data["workout_flags"],
        "sleep_perf": data["sleep_perf"],
        "training_base": data["training_base"],
        "display": data["display"],
        "data_meta": data.get("data_meta"),
        "science_notes": data.get("science_notes"),
    }
