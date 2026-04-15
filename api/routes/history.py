"""Activity history endpoint."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from api.auth import get_current_user_id
from api.deps import get_dashboard_data
from db.session import get_db

router = APIRouter()


@router.get("/history")
def get_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    data = get_dashboard_data(user_id=user_id, db=db)
    activities = data["activities"]
    total = len(activities)
    page = activities[offset : offset + limit]
    return {
        "activities": page,
        "total": total,
        "limit": limit,
        "offset": offset,
        "training_base": data["training_base"],
        "display": data["display"],
    }
