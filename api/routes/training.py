"""Training analysis endpoint."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from api.auth import get_data_user_id
from api.packs import RequestContext, get_diagnosis_pack, get_fitness_pack
from db.session import get_db

router = APIRouter()


@router.get("/training")
def get_training(
    user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
):
    ctx = RequestContext(user_id=user_id, db=db)
    diagnosis = get_diagnosis_pack(ctx)
    fitness = get_fitness_pack(ctx)
    return {
        "diagnosis": diagnosis["diagnosis"],
        "fitness_fatigue": fitness["fitness_fatigue"],
        "cp_trend": fitness["cp_trend"],
        "weekly_review": fitness["weekly_review"],
        "workout_flags": diagnosis["workout_flags"],
        "sleep_perf": diagnosis["sleep_perf"],
        "training_base": ctx.config.training_base,
        "display": ctx.display,
        "data_meta": ctx.data_meta,
        "science_notes": ctx.science_notes,
    }
