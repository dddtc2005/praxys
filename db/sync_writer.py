"""Write sync data directly to the database, bypassing CSVs.

Each function takes parsed row dicts (same format the sync parse functions
produce) and upserts them into the appropriate DB tables.
"""
import logging
from datetime import date, datetime

from sqlalchemy.orm import Session

from db.models import Activity, ActivitySplit, RecoveryData, FitnessData, TrainingPlan

logger = logging.getLogger(__name__)


def _parse_date(val) -> date | None:
    if val is None or val == "":
        return None
    if isinstance(val, date):
        return val
    try:
        return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _float(val) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _str(val) -> str | None:
    if val is None or val == "":
        return None
    return str(val)


def write_activities(user_id: str, rows: list[dict], db: Session) -> int:
    """Write activity rows to DB. Skips existing (by activity_id). Returns count of new."""
    if not rows:
        return 0
    existing_ids = {
        r[0] for r in db.query(Activity.activity_id).filter(
            Activity.user_id == user_id
        ).all()
    }
    count = 0
    for row in rows:
        aid = _str(row.get("activity_id"))
        if not aid or aid in existing_ids:
            continue
        db.add(Activity(
            user_id=user_id,
            activity_id=aid,
            date=_parse_date(row.get("date")),
            activity_type=_str(row.get("activity_type")) or "running",
            distance_km=_float(row.get("distance_km")),
            duration_sec=_float(row.get("duration_sec")),
            avg_power=_float(row.get("avg_power")),
            max_power=_float(row.get("max_power")),
            avg_hr=_float(row.get("avg_hr")),
            max_hr=_float(row.get("max_hr")),
            avg_pace_min_km=_str(row.get("avg_pace_min_km")),
            elevation_gain_m=_float(row.get("elevation_gain_m")),
            avg_cadence=_float(row.get("avg_cadence")),
            training_effect=_float(row.get("aerobic_te") or row.get("training_effect")),
            rss=_float(row.get("rss")),
            cp_estimate=_float(row.get("cp_estimate")),
            start_time=_str(row.get("start_time")),
            source=_str(row.get("source")) or "garmin",
        ))
        existing_ids.add(aid)
        count += 1
    return count


def write_splits(user_id: str, rows: list[dict], db: Session) -> int:
    """Write split rows to DB. Skips existing. Returns count of new."""
    if not rows:
        return 0
    existing = {
        (r[0], r[1]) for r in db.query(
            ActivitySplit.activity_id, ActivitySplit.split_num
        ).filter(ActivitySplit.user_id == user_id).all()
    }
    count = 0
    for row in rows:
        aid = _str(row.get("activity_id"))
        snum = row.get("split_num")
        if not aid or snum is None:
            continue
        snum = int(snum)
        if (aid, snum) in existing:
            continue
        db.add(ActivitySplit(
            user_id=user_id,
            activity_id=aid,
            split_num=snum,
            distance_km=_float(row.get("distance_km")),
            duration_sec=_float(row.get("duration_sec")),
            avg_power=_float(row.get("avg_power")),
            avg_hr=_float(row.get("avg_hr")),
            max_hr=_float(row.get("max_hr")),
            avg_pace_min_km=_str(row.get("avg_pace_min_km")),
            avg_cadence=_float(row.get("avg_cadence")),
            elevation_change_m=_float(row.get("elevation_change_m")),
        ))
        existing.add((aid, snum))
        count += 1
    return count


def write_recovery(user_id: str, readiness_rows: list[dict],
                   sleep_rows: list[dict], hrv_by_date: dict,
                   db: Session,
                   garmin_recovery: list[dict] | None = None) -> int:
    """Write recovery data (readiness + sleep merged) to DB. Returns count of new.

    Supports both Oura (readiness_rows + sleep_rows + hrv_by_date) and
    Garmin (garmin_recovery list with pre-parsed fields).
    """
    count = 0

    # --- Oura recovery ---
    existing_oura = {
        r[0] for r in db.query(RecoveryData.date).filter(
            RecoveryData.user_id == user_id, RecoveryData.source == "oura"
        ).all()
    }

    sleep_by_date = {}
    for row in sleep_rows:
        d = row.get("date", "")
        if d:
            sleep_by_date[d] = row

    for row in readiness_rows:
        d = _parse_date(row.get("date"))
        if not d or d in existing_oura:
            continue
        sleep = sleep_by_date.get(row.get("date", ""), {})
        hrv = hrv_by_date.get(row.get("date", ""), {})
        db.add(RecoveryData(
            user_id=user_id, date=d, source="oura",
            readiness_score=_float(row.get("readiness_score")),
            hrv_avg=_float(hrv.get("hrv_avg") or row.get("hrv_avg")),
            resting_hr=_float(hrv.get("resting_hr") or row.get("resting_hr")),
            sleep_score=_float(sleep.get("sleep_score")),
            total_sleep_sec=_float(sleep.get("total_sleep_sec")),
            deep_sleep_sec=_float(sleep.get("deep_sleep_sec")),
            rem_sleep_sec=_float(sleep.get("rem_sleep_sec")),
            body_temp_delta=_float(
                row.get("body_temperature_delta") or row.get("body_temp_delta")
            ),
        ))
        existing_oura.add(d)
        count += 1

    # --- Garmin recovery ---
    if garmin_recovery:
        existing_garmin = {
            r[0] for r in db.query(RecoveryData.date).filter(
                RecoveryData.user_id == user_id, RecoveryData.source == "garmin"
            ).all()
        }
        for row in garmin_recovery:
            d = _parse_date(row.get("date"))
            if not d:
                continue
            if d in existing_garmin:
                # Update existing
                existing = db.query(RecoveryData).filter(
                    RecoveryData.user_id == user_id,
                    RecoveryData.date == d,
                    RecoveryData.source == "garmin",
                ).first()
                if existing:
                    if row.get("readiness_score"):
                        existing.readiness_score = _float(row["readiness_score"])
                    if row.get("hrv_ms"):
                        existing.hrv_avg = _float(row["hrv_ms"])
                    if row.get("resting_hr"):
                        existing.resting_hr = _float(row["resting_hr"])
                    if row.get("sleep_score"):
                        existing.sleep_score = _float(row["sleep_score"])
                    if row.get("total_sleep_hours"):
                        existing.total_sleep_sec = _float(row["total_sleep_hours"]) * 3600 if _float(row["total_sleep_hours"]) else None
                    count += 1
            else:
                total_sleep_sec = None
                if row.get("total_sleep_hours"):
                    h = _float(row["total_sleep_hours"])
                    total_sleep_sec = h * 3600 if h else None
                db.add(RecoveryData(
                    user_id=user_id, date=d, source="garmin",
                    readiness_score=_float(row.get("readiness_score")),
                    hrv_avg=_float(row.get("hrv_ms")),
                    resting_hr=_float(row.get("resting_hr")),
                    sleep_score=_float(row.get("sleep_score")),
                    total_sleep_sec=total_sleep_sec,
                ))
                existing_garmin.add(d)
                count += 1

    return count


def write_daily_metrics(user_id: str, rows: list[dict], db: Session) -> int:
    """Write Garmin daily metrics to fitness_data table. Returns count of new."""
    count = 0
    metrics = [
        ("vo2max", "vo2max", False),
        ("training_status", "training_status", True),
        ("resting_hr", "rest_hr_bpm", False),
        ("training_readiness", "training_readiness", False),
    ]
    for row in rows:
        d = _parse_date(row.get("date"))
        if not d:
            continue
        for csv_col, metric_type, is_str in metrics:
            val = row.get(csv_col)
            if val is None or val == "":
                continue
            exists = db.query(FitnessData.id).filter(
                FitnessData.user_id == user_id,
                FitnessData.date == d,
                FitnessData.metric_type == metric_type,
            ).first()
            if exists:
                continue
            db.add(FitnessData(
                user_id=user_id, date=d, metric_type=metric_type, source="garmin",
                value=None if is_str else _float(val),
                value_str=_str(val) if is_str else None,
            ))
            count += 1
    return count


def write_lactate_threshold(user_id: str, rows: list[dict], db: Session) -> int:
    """Write lactate threshold data to fitness_data table. Returns count of new."""
    count = 0
    for row in rows:
        d = _parse_date(row.get("date"))
        if not d:
            continue
        for csv_col, metric_type in [
            ("lthr_bpm", "lthr_bpm"),
            ("lt_power_watts", "lt_power_watts"),
            ("lt_pace_sec_km", "lt_pace_sec_km"),
        ]:
            val = row.get(csv_col)
            if val is None or val == "":
                continue
            exists = db.query(FitnessData.id).filter(
                FitnessData.user_id == user_id,
                FitnessData.date == d,
                FitnessData.metric_type == metric_type,
            ).first()
            if exists:
                continue
            db.add(FitnessData(
                user_id=user_id, date=d, metric_type=metric_type,
                value=_float(val), source="garmin",
            ))
            count += 1
    return count


def write_training_plan(user_id: str, rows: list[dict], source: str,
                        db: Session) -> int:
    """Write training plan rows to DB. Returns count of new."""
    if not rows:
        return 0
    count = 0
    for row in rows:
        d = _parse_date(row.get("date"))
        if not d:
            continue
        wt = _str(row.get("workout_type"))
        exists = db.query(TrainingPlan.id).filter(
            TrainingPlan.user_id == user_id,
            TrainingPlan.date == d,
            TrainingPlan.source == source,
            TrainingPlan.workout_type == wt,
        ).first()
        if exists:
            continue
        db.add(TrainingPlan(
            user_id=user_id, date=d, source=source,
            workout_type=wt,
            planned_duration_min=_float(row.get("planned_duration_min")),
            planned_distance_km=_float(row.get("planned_distance_km")),
            target_power_min=_float(row.get("target_power_min")),
            target_power_max=_float(row.get("target_power_max")),
            workout_description=_str(row.get("workout_description")),
        ))
        count += 1
    return count
