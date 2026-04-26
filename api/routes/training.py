"""Training analysis endpoint."""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from api.auth import get_data_user_id
from api.dashboard_cache import cached_or_compute
from api.etag import ETagGuard, etag_guard_for_endpoint
from api.packs import RequestContext, get_diagnosis_pack, get_fitness_pack
from db.session import get_db

router = APIRouter()


def _build_training_payload(user_id: str, db: Session) -> dict:
    """Compute the /api/training response from L1 packs (cache miss path)."""
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


@router.get("/training")
def get_training(
    response: Response,
    guard: ETagGuard = Depends(etag_guard_for_endpoint("training")),
    user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
):
    if guard.is_match:
        return guard.not_modified()
    guard.apply(response)
    return cached_or_compute(
        db, user_id, "training",
        compute=lambda: _build_training_payload(user_id, db),
    )
