"""AI-related endpoints: training context and plan upload."""
import csv
import io
from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_data_user_id, require_write_access
from api.deps import get_dashboard_data
from db.session import get_db

router = APIRouter()


@router.get("/ai/context")
def get_ai_context(
    user_id: str = Depends(get_data_user_id),
    db: Session = Depends(get_db),
):
    """Return full training context for AI plan generation."""
    data = get_dashboard_data(user_id=user_id, db=db)
    from api.ai import _build_context_from_data
    return _build_context_from_data(data)


class PlanUpload(BaseModel):
    csv: str


@router.post("/plan/upload")
def upload_plan(
    payload: PlanUpload,
    user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
):
    """Upload an AI-generated training plan as CSV text.

    Replaces future AI plan entries for this user while preserving past ones.
    """
    from db.models import TrainingPlan

    reader = csv.DictReader(io.StringIO(payload.csv))
    rows = list(reader)

    if not rows:
        return {"status": "error", "message": "No rows in CSV"}

    # Validate all rows first (before deleting existing plan)
    parsed_rows = []
    for i, row in enumerate(rows):
        try:
            parsed_rows.append(TrainingPlan(
                user_id=user_id,
                date=datetime.strptime(row.get("date", ""), "%Y-%m-%d").date() if row.get("date") else None,
                workout_type=row.get("workout_type", ""),
                planned_duration_min=float(row.get("planned_duration_min", 0)) if row.get("planned_duration_min") else None,
                target_power_min=float(row.get("target_power_min", 0)) if row.get("target_power_min") else None,
                target_power_max=float(row.get("target_power_max", 0)) if row.get("target_power_max") else None,
                workout_description=row.get("workout_description", ""),
                source="ai",
                meta={"uploaded_at": datetime.utcnow().isoformat()},
            ))
        except (ValueError, TypeError) as e:
            raise HTTPException(400, f"Invalid data in row {i + 1}: {e}")

    # Delete future AI plan entries only after validation succeeds
    db.query(TrainingPlan).filter(
        TrainingPlan.user_id == user_id,
        TrainingPlan.source == "ai",
        TrainingPlan.date >= date.today(),
    ).delete()

    for plan in parsed_rows:
        db.add(plan)

    db.commit()
    return {"status": "saved", "rows": len(parsed_rows)}
