"""Import CSV data into the database for a specific user.

Called after each sync to bridge the gap between sync scripts (which write CSVs)
and the app (which reads from DB). Safe to call repeatedly — only inserts new records.
"""
import logging
import os
from datetime import date

import pandas as pd
from sqlalchemy.orm import Session

from db.models import (
    Activity, ActivitySplit, RecoveryData, FitnessData, TrainingPlan,
)

logger = logging.getLogger(__name__)


def _parse_date(val) -> date | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, date):
        return val
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None


def _safe_float(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return f if pd.notna(f) else None
    except (ValueError, TypeError):
        return None


def _safe_str(val) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    return str(val)


def _read_csv(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    return df


def import_csvs_for_user(user_id: str, data_dir: str, db: Session) -> dict:
    """Import CSV data into the DB for a user. Returns counts of new records.

    Safe to call repeatedly — checks for existing records via unique constraints.
    """
    counts = {"activities": 0, "splits": 0, "recovery": 0, "fitness": 0, "plan": 0}

    # --- Activities (Garmin + Stryd merged) ---
    garmin_df = _read_csv(os.path.join(data_dir, "garmin", "activities.csv"))
    stryd_df = _read_csv(os.path.join(data_dir, "stryd", "power_data.csv"))

    if not garmin_df.empty and not stryd_df.empty:
        from analysis.data_loader import match_activities
        merged = match_activities(garmin_df, stryd_df)
    elif not garmin_df.empty:
        merged = garmin_df
    elif not stryd_df.empty:
        merged = stryd_df
    else:
        merged = pd.DataFrame()

    for _, row in merged.iterrows():
        d = _parse_date(row.get("date"))
        aid = _safe_str(row.get("activity_id"))
        if not d or not aid:
            continue
        exists = db.query(Activity.id).filter(
            Activity.user_id == user_id, Activity.activity_id == aid
        ).first()
        if exists:
            continue
        db.add(Activity(
            user_id=user_id, activity_id=aid, date=d,
            activity_type=_safe_str(row.get("activity_type")) or "running",
            distance_km=_safe_float(row.get("distance_km")),
            duration_sec=_safe_float(row.get("duration_sec")),
            avg_power=_safe_float(row.get("avg_power")),
            max_power=_safe_float(row.get("max_power")),
            avg_hr=_safe_float(row.get("avg_hr")),
            max_hr=_safe_float(row.get("max_hr")),
            avg_pace_min_km=_safe_str(row.get("avg_pace_min_km")),
            avg_pace_sec_km=_safe_float(row.get("avg_pace_sec_km")),
            elevation_gain_m=_safe_float(row.get("elevation_gain_m")),
            avg_cadence=_safe_float(row.get("avg_cadence")),
            training_effect=_safe_float(row.get("training_effect")),
            rss=_safe_float(row.get("rss")),
            cp_estimate=_safe_float(row.get("cp_estimate")),
            start_time=_safe_str(row.get("start_time")),
            source="garmin",
        ))
        counts["activities"] += 1

    # --- Splits ---
    splits_df = _read_csv(os.path.join(data_dir, "garmin", "activity_splits.csv"))
    existing_splits = set()
    if not splits_df.empty:
        rows = db.query(ActivitySplit.activity_id, ActivitySplit.split_num).filter(
            ActivitySplit.user_id == user_id
        ).all()
        existing_splits = {(r[0], r[1]) for r in rows}

    for _, row in splits_df.iterrows():
        aid = _safe_str(row.get("activity_id"))
        snum = row.get("split_num")
        if not aid or snum is None:
            continue
        if (aid, int(snum)) in existing_splits:
            continue
        db.add(ActivitySplit(
            user_id=user_id, activity_id=aid, split_num=int(snum),
            distance_km=_safe_float(row.get("distance_km")),
            duration_sec=_safe_float(row.get("duration_sec")),
            avg_power=_safe_float(row.get("avg_power")),
            avg_hr=_safe_float(row.get("avg_hr")),
            max_hr=_safe_float(row.get("max_hr")),
            avg_pace_min_km=_safe_str(row.get("avg_pace_min_km")),
            avg_pace_sec_km=_safe_float(row.get("avg_pace_sec_km")),
            avg_cadence=_safe_float(row.get("avg_cadence")),
            elevation_change_m=_safe_float(row.get("elevation_change_m")),
        ))
        counts["splits"] += 1

    # --- Recovery (Oura) ---
    readiness_df = _read_csv(os.path.join(data_dir, "oura", "readiness.csv"))
    sleep_df = _read_csv(os.path.join(data_dir, "oura", "sleep.csv"))

    existing_recovery_dates = set()
    if not readiness_df.empty or not sleep_df.empty:
        rows = db.query(RecoveryData.date).filter(
            RecoveryData.user_id == user_id, RecoveryData.source == "oura"
        ).all()
        existing_recovery_dates = {r[0] for r in rows}

    for _, row in readiness_df.iterrows():
        d = _parse_date(row.get("date"))
        if not d or d in existing_recovery_dates:
            continue
        sleep_row = {}
        if not sleep_df.empty and "date" in sleep_df.columns:
            match = sleep_df[sleep_df["date"] == d]
            if not match.empty:
                sleep_row = match.iloc[0].to_dict()
        db.add(RecoveryData(
            user_id=user_id, date=d, source="oura",
            readiness_score=_safe_float(row.get("readiness_score")),
            hrv_avg=_safe_float(row.get("hrv_avg")),
            resting_hr=_safe_float(row.get("resting_hr")),
            sleep_score=_safe_float(sleep_row.get("sleep_score")),
            total_sleep_sec=_safe_float(sleep_row.get("total_sleep_sec")),
            deep_sleep_sec=_safe_float(sleep_row.get("deep_sleep_sec")),
            rem_sleep_sec=_safe_float(sleep_row.get("rem_sleep_sec")),
        ))
        existing_recovery_dates.add(d)
        counts["recovery"] += 1

    # --- Fitness (Garmin daily metrics) ---
    daily_df = _read_csv(os.path.join(data_dir, "garmin", "daily_metrics.csv"))
    for _, row in daily_df.iterrows():
        d = _parse_date(row.get("date"))
        if not d:
            continue
        for csv_col, metric_type, is_str in [
            ("vo2max", "vo2max", False),
            ("training_status", "training_status", True),
            ("resting_hr", "rest_hr_bpm", False),
        ]:
            val = row.get(csv_col)
            if val is None or (isinstance(val, float) and pd.isna(val)):
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
                value=None if is_str else _safe_float(val),
                value_str=_safe_str(val) if is_str else None,
            ))
            counts["fitness"] += 1

    # --- Training plan (Stryd) ---
    plan_df = _read_csv(os.path.join(data_dir, "stryd", "training_plan.csv"))
    for _, row in plan_df.iterrows():
        d = _parse_date(row.get("date"))
        if not d:
            continue
        wt = _safe_str(row.get("workout_type"))
        exists = db.query(TrainingPlan.id).filter(
            TrainingPlan.user_id == user_id,
            TrainingPlan.date == d,
            TrainingPlan.source == "stryd",
            TrainingPlan.workout_type == wt,
        ).first()
        if exists:
            continue
        db.add(TrainingPlan(
            user_id=user_id, date=d, source="stryd",
            workout_type=wt,
            planned_duration_min=_safe_float(row.get("planned_duration_min")),
            target_power_min=_safe_float(row.get("target_power_min")),
            target_power_max=_safe_float(row.get("target_power_max")),
            workout_description=_safe_str(row.get("workout_description")),
        ))
        counts["plan"] += 1

    db.commit()
    return counts
