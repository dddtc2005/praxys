"""AI-related endpoints: training context, plan upload, per-day upsert/delete."""
import csv
import io
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_data_user_id, require_write_access
from api.deps import get_dashboard_data
from db.cache_revision import bump_revisions
from db.models import TrainingPlan
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


class PlanWorkout(BaseModel):
    """Single-day workout payload for `PUT /api/plan/{plan_date}`."""

    workout_type: str
    planned_duration_min: Optional[float] = None
    planned_distance_km: Optional[float] = None
    target_power_min: Optional[float] = None
    target_power_max: Optional[float] = None
    workout_description: Optional[str] = None


def _row_to_response(plan: TrainingPlan) -> dict:
    return {
        "id": plan.id,
        "date": plan.date.isoformat() if plan.date else None,
        "workout_type": plan.workout_type,
        "planned_duration_min": plan.planned_duration_min,
        "planned_distance_km": plan.planned_distance_km,
        "target_power_min": plan.target_power_min,
        "target_power_max": plan.target_power_max,
        "workout_description": plan.workout_description,
        "source": plan.source,
    }


def _parse_csv_row(row: dict, row_index: int) -> dict:
    """Parse one CSV dict-row into TrainingPlan kwargs (without user_id)."""
    try:
        d_raw = row.get("date", "")
        d = datetime.strptime(d_raw, "%Y-%m-%d").date() if d_raw else None
        return {
            "date": d,
            "workout_type": row.get("workout_type", ""),
            "planned_duration_min": float(row["planned_duration_min"])
                if row.get("planned_duration_min") else None,
            "planned_distance_km": float(row["planned_distance_km"])
                if row.get("planned_distance_km") else None,
            "target_power_min": float(row["target_power_min"])
                if row.get("target_power_min") else None,
            "target_power_max": float(row["target_power_max"])
                if row.get("target_power_max") else None,
            "workout_description": row.get("workout_description", ""),
        }
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"Invalid data in row {row_index + 1}: {e}")


@router.post("/plan/upload")
def upload_plan(
    payload: PlanUpload,
    mode: str = Query("replace", pattern="^(replace|merge)$"),
    user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
):
    """Upload an AI-generated training plan as CSV text.

    `mode=replace` (default, backwards-compatible): delete every future AI
    plan row for the user, then insert the payload. Past rows are preserved.

    `mode=merge`: upsert by `(user, date, source='ai')` — only the dates
    present in the payload are touched; all other AI rows (past and future)
    are left alone. Use this when shifting or editing individual workouts
    without resending the whole plan window.
    """
    reader = csv.DictReader(io.StringIO(payload.csv))
    rows = list(reader)

    if not rows:
        return {"status": "error", "message": "No rows in CSV"}

    parsed_rows = []
    for i, row in enumerate(rows):
        kwargs = _parse_csv_row(row, i)
        parsed_rows.append(TrainingPlan(
            user_id=user_id,
            source="ai",
            meta={"uploaded_at": datetime.utcnow().isoformat()},
            **kwargs,
        ))

    if mode == "replace":
        db.query(TrainingPlan).filter(
            TrainingPlan.user_id == user_id,
            TrainingPlan.source == "ai",
            TrainingPlan.date >= date.today(),
        ).delete(synchronize_session=False)
    else:  # merge: clear only the dates we're about to write
        target_dates = {p.date for p in parsed_rows if p.date is not None}
        if target_dates:
            db.query(TrainingPlan).filter(
                TrainingPlan.user_id == user_id,
                TrainingPlan.source == "ai",
                TrainingPlan.date.in_(target_dates),
            ).delete(synchronize_session=False)

    for plan in parsed_rows:
        db.add(plan)

    bump_revisions(db, user_id, ["plans"])
    db.commit()
    return {"status": "saved", "rows": len(parsed_rows), "mode": mode}


@router.put("/plan/{plan_date}")
def upsert_plan_day(
    plan_date: str,
    workout: PlanWorkout,
    user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
):
    """Upsert a single AI plan workout for the given date (YYYY-MM-DD).

    Replaces any existing AI rows for `(user, date)` with one new row from
    the payload. Other dates are untouched. Use this for partial edits —
    e.g. shifting a single workout — instead of round-tripping the whole
    future plan via /plan/upload.
    """
    try:
        d = datetime.strptime(plan_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")

    db.query(TrainingPlan).filter(
        TrainingPlan.user_id == user_id,
        TrainingPlan.source == "ai",
        TrainingPlan.date == d,
    ).delete(synchronize_session=False)

    plan = TrainingPlan(
        user_id=user_id,
        date=d,
        workout_type=workout.workout_type,
        planned_duration_min=workout.planned_duration_min,
        planned_distance_km=workout.planned_distance_km,
        target_power_min=workout.target_power_min,
        target_power_max=workout.target_power_max,
        workout_description=workout.workout_description or "",
        source="ai",
        meta={"uploaded_at": datetime.utcnow().isoformat()},
    )
    db.add(plan)
    bump_revisions(db, user_id, ["plans"])
    db.commit()
    db.refresh(plan)
    return _row_to_response(plan)


@router.delete("/plan/{plan_date}")
def delete_plan_day(
    plan_date: str,
    user_id: str = Depends(require_write_access),
    db: Session = Depends(get_db),
):
    """Delete the AI plan workout(s) for the given date (YYYY-MM-DD)."""
    try:
        d = datetime.strptime(plan_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")

    deleted = db.query(TrainingPlan).filter(
        TrainingPlan.user_id == user_id,
        TrainingPlan.source == "ai",
        TrainingPlan.date == d,
    ).delete(synchronize_session=False)
    if deleted:
        bump_revisions(db, user_id, ["plans"])
    db.commit()
    return {"status": "deleted", "rows": deleted, "date": plan_date}
