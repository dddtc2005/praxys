"""Migrate existing CSV data and config.json into the SQLite database.

Usage:
    python -m scripts.migrate_csv_to_db [--data-dir DATA_DIR] [--email EMAIL]

This script:
1. Reads existing CSVs from the data/ directory
2. Creates a user (with provided or default email/password)
3. Inserts all CSV data into the appropriate DB tables
4. Creates a UserConfig from existing data/config.json
5. Creates UserConnection entries based on existing connections
"""
import argparse
import json
import logging
import os
import sys
from datetime import date, datetime

import pandas as pd

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.models import (
    Base,
    User,
    UserConfig,
    UserConnection,
    Activity,
    ActivitySplit,
    RecoveryData,
    FitnessData,
    TrainingPlan,
)
import db.session as db_session
from analysis.config import load_config, DEFAULT_ZONES
from analysis.data_loader import load_all_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _parse_date(val) -> date | None:
    """Parse a date value from various formats."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, date):
        return val
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None


def _safe_float(val) -> float | None:
    """Safely convert a value to float, returning None on failure."""
    if val is None:
        return None
    try:
        f = float(val)
        return f if pd.notna(f) else None
    except (ValueError, TypeError):
        return None


def _safe_str(val) -> str | None:
    """Safely convert a value to string, returning None for NaN."""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    return str(val)


def migrate(data_dir: str, email: str = "local@praxys.dev", password: str = "changeme"):
    """Run the full CSV-to-DB migration."""
    # Set DATA_DIR so init_db creates the DB in the right place
    os.environ["DATA_DIR"] = data_dir
    db_session.init_db()
    db = db_session.SessionLocal()

    try:
        # --- Step 1: Find or create user ---
        # First check if a user with this email already exists (e.g., dev user)
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            user_id = existing.id
            logger.info("Using existing user: %s (%s)", user_id, email)
        else:
            # Also check by the legacy migration ID
            user_id = "migrated-user-00000001"
            existing = db.query(User).filter(User.id == user_id).first()
            if existing:
                user_id = existing.id
                logger.info("Using existing migrated user: %s", user_id)
            else:
                logger.info("Creating user: %s (%s)", user_id, email)
                user = User(
                    id=user_id,
                    email=email,
                    hashed_password=f"migration-placeholder:{password}",
                    is_active=True,
                    is_superuser=False,
                    is_verified=True,
                )
                db.add(user)
                db.flush()

        # --- Step 2: Load and migrate config.json ---
        config = load_config(os.path.join(data_dir, "config.json"))
        existing_cfg = db.query(UserConfig).filter(UserConfig.user_id == user_id).first()
        if not existing_cfg:
            logger.info("Migrating config.json...")
            cfg = UserConfig(
                user_id=user_id,
                training_base=config.training_base,
                thresholds=config.thresholds,
                zones=config.zones or {k: list(v) for k, v in DEFAULT_ZONES.items()},
                goal=config.goal,
                science=config.science,
                zone_labels=config.zone_labels,
                activity_routing=config.activity_routing,
                source_options=config.source_options,
            )
            db.add(cfg)
            db.flush()

        # --- Step 3: Create UserConnection entries ---
        for platform in config.connections:
            exists = (
                db.query(UserConnection)
                .filter(
                    UserConnection.user_id == user_id,
                    UserConnection.platform == platform,
                )
                .first()
            )
            if not exists:
                logger.info("Creating connection: %s", platform)
                prefs = {}
                from analysis.config import PLATFORM_CAPABILITIES
                caps = PLATFORM_CAPABILITIES.get(platform, {})
                for cap_name, has_cap in caps.items():
                    if has_cap:
                        prefs[cap_name] = True
                conn = UserConnection(
                    user_id=user_id,
                    platform=platform,
                    status="connected",
                    preferences=prefs,
                )
                db.add(conn)
            db.flush()

        # --- Step 4: Load CSV data ---
        logger.info("Loading CSV data from %s...", data_dir)
        raw = load_all_data(data_dir)

        # --- Step 5: Migrate activities ---
        garmin_df = raw.get("garmin_activities", pd.DataFrame())
        stryd_df = raw.get("stryd_power", pd.DataFrame())

        # Merge Garmin + Stryd for combined activity data
        from analysis.data_loader import match_activities
        if not garmin_df.empty and not stryd_df.empty:
            merged = match_activities(garmin_df, stryd_df)
        elif not garmin_df.empty:
            merged = garmin_df
        elif not stryd_df.empty:
            merged = stryd_df
        else:
            merged = pd.DataFrame()

        act_count = 0
        for _, row in merged.iterrows():
            d = _parse_date(row.get("date"))
            aid = _safe_str(row.get("activity_id"))
            if not d or not aid:
                continue
            exists = (
                db.query(Activity)
                .filter(Activity.user_id == user_id, Activity.activity_id == aid)
                .first()
            )
            if exists:
                continue
            act = Activity(
                user_id=user_id,
                activity_id=aid,
                date=d,
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
                trimp=_safe_float(row.get("trimp")),
                rtss=_safe_float(row.get("rtss")),
                cp_estimate=_safe_float(row.get("cp_estimate")),
                load_score=_safe_float(row.get("load_score")),
                start_time=_safe_str(row.get("start_time")),
                source="garmin",
            )
            db.add(act)
            act_count += 1
        logger.info("Migrated %d activities", act_count)

        # --- Step 6: Migrate splits ---
        splits_df = raw.get("garmin_splits", pd.DataFrame())
        split_count = 0
        for _, row in splits_df.iterrows():
            aid = _safe_str(row.get("activity_id"))
            snum = row.get("split_num")
            if not aid or snum is None:
                continue
            sp = ActivitySplit(
                user_id=user_id,
                activity_id=aid,
                split_num=int(snum),
                distance_km=_safe_float(row.get("distance_km")),
                duration_sec=_safe_float(row.get("duration_sec")),
                avg_power=_safe_float(row.get("avg_power")),
                avg_hr=_safe_float(row.get("avg_hr")),
                max_hr=_safe_float(row.get("max_hr")),
                avg_pace_min_km=_safe_str(row.get("avg_pace_min_km")),
                avg_pace_sec_km=_safe_float(row.get("avg_pace_sec_km")),
                avg_cadence=_safe_float(row.get("avg_cadence")),
                elevation_change_m=_safe_float(row.get("elevation_change_m")),
            )
            db.add(sp)
            split_count += 1
        logger.info("Migrated %d splits", split_count)

        # --- Step 7: Migrate recovery data (Oura sleep + readiness) ---
        sleep_df = raw.get("oura_sleep", pd.DataFrame())
        readiness_df = raw.get("oura_readiness", pd.DataFrame())

        # Merge sleep + readiness on date
        recovery_count = 0
        recovery_dates = set()
        if not readiness_df.empty:
            for _, row in readiness_df.iterrows():
                d = _parse_date(row.get("date"))
                if not d:
                    continue
                recovery_dates.add(d)
                # Try to find matching sleep data for the same date
                sleep_row = {}
                if not sleep_df.empty and "date" in sleep_df.columns:
                    match = sleep_df[sleep_df["date"] == d]
                    if not match.empty:
                        sleep_row = match.iloc[0].to_dict()

                rec = RecoveryData(
                    user_id=user_id,
                    date=d,
                    readiness_score=_safe_float(row.get("readiness_score")),
                    hrv_avg=_safe_float(row.get("hrv_avg")),
                    resting_hr=_safe_float(row.get("resting_hr")),
                    sleep_score=_safe_float(sleep_row.get("sleep_score")),
                    total_sleep_sec=_safe_float(sleep_row.get("total_sleep_sec")),
                    deep_sleep_sec=_safe_float(sleep_row.get("deep_sleep_sec")),
                    rem_sleep_sec=_safe_float(sleep_row.get("rem_sleep_sec")),
                    body_temp_delta=_safe_float(
                        row.get("body_temperature_delta") or row.get("body_temp_delta")
                    ),
                    source="oura",
                )
                db.add(rec)
                recovery_count += 1

        # Add any sleep dates not covered by readiness
        if not sleep_df.empty:
            for _, row in sleep_df.iterrows():
                d = _parse_date(row.get("date"))
                if not d or d in recovery_dates:
                    continue
                rec = RecoveryData(
                    user_id=user_id,
                    date=d,
                    sleep_score=_safe_float(row.get("sleep_score")),
                    total_sleep_sec=_safe_float(row.get("total_sleep_sec")),
                    deep_sleep_sec=_safe_float(row.get("deep_sleep_sec")),
                    rem_sleep_sec=_safe_float(row.get("rem_sleep_sec")),
                    source="oura",
                )
                db.add(rec)
                recovery_count += 1
        logger.info("Migrated %d recovery records", recovery_count)

        # --- Step 8: Migrate fitness data (Garmin daily metrics) ---
        daily_df = raw.get("garmin_daily", pd.DataFrame())
        fitness_count = 0
        fitness_metrics = [
            ("vo2max", "vo2max", False),
            ("training_status", "training_status", True),
            ("resting_hr", "rest_hr_bpm", False),
        ]
        for _, row in daily_df.iterrows():
            d = _parse_date(row.get("date"))
            if not d:
                continue
            for csv_col, metric_type, is_str in fitness_metrics:
                val = row.get(csv_col)
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    continue
                fd = FitnessData(
                    user_id=user_id,
                    date=d,
                    metric_type=metric_type,
                    value=None if is_str else _safe_float(val),
                    value_str=_safe_str(val) if is_str else None,
                    source="garmin",
                )
                db.add(fd)
                fitness_count += 1

        # CP estimates from Stryd (deduplicate by date — keep last per date)
        if not stryd_df.empty and "cp_estimate" in stryd_df.columns:
            cp_by_date: dict = {}
            for _, row in stryd_df.iterrows():
                d = _parse_date(row.get("date"))
                cp = _safe_float(row.get("cp_estimate"))
                if d and cp:
                    cp_by_date[d] = cp  # last wins
            for d, cp in cp_by_date.items():
                fd = FitnessData(
                    user_id=user_id,
                    date=d,
                    metric_type="cp_estimate",
                    value=cp,
                    source="stryd",
                )
                db.add(fd)
                fitness_count += 1
        logger.info("Migrated %d fitness records", fitness_count)

        # --- Step 9: Migrate training plan ---
        plan_df = raw.get("stryd_plan", pd.DataFrame())
        plan_count = 0
        for _, row in plan_df.iterrows():
            d = _parse_date(row.get("date"))
            if not d:
                continue
            tp = TrainingPlan(
                user_id=user_id,
                date=d,
                workout_type=_safe_str(row.get("workout_type")),
                planned_duration_min=_safe_float(row.get("planned_duration_min")),
                planned_distance_km=_safe_float(row.get("planned_distance_km")),
                target_power_min=_safe_float(row.get("target_power_min")),
                target_power_max=_safe_float(row.get("target_power_max")),
                target_hr_min=_safe_float(row.get("target_hr_min")),
                target_hr_max=_safe_float(row.get("target_hr_max")),
                target_pace_min=_safe_str(row.get("target_pace_min")),
                target_pace_max=_safe_str(row.get("target_pace_max")),
                workout_description=_safe_str(row.get("workout_description")),
                source="stryd",
            )
            db.add(tp)
            plan_count += 1

        # Also check for AI plans
        ai_plan_path = os.path.join(data_dir, "ai", "training_plan.csv")
        if os.path.exists(ai_plan_path):
            ai_plan_df = pd.read_csv(ai_plan_path)
            if "date" in ai_plan_df.columns:
                ai_plan_df["date"] = pd.to_datetime(ai_plan_df["date"]).dt.date
                for _, row in ai_plan_df.iterrows():
                    d = _parse_date(row.get("date"))
                    if not d:
                        continue
                    tp = TrainingPlan(
                        user_id=user_id,
                        date=d,
                        workout_type=_safe_str(row.get("workout_type")),
                        planned_duration_min=_safe_float(row.get("planned_duration_min")),
                        planned_distance_km=_safe_float(row.get("planned_distance_km")),
                        target_power_min=_safe_float(row.get("target_power_min")),
                        target_power_max=_safe_float(row.get("target_power_max")),
                        workout_description=_safe_str(row.get("workout_description")),
                        source="ai",
                    )
                    db.add(tp)
                    plan_count += 1
        logger.info("Migrated %d plan records", plan_count)

        db.commit()
        logger.info("Migration complete! Database: %s", os.path.join(data_dir, "trainsight.db"))

    except Exception:
        db.rollback()
        logger.exception("Migration failed!")
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Migrate CSV data to SQLite database")
    parser.add_argument(
        "--data-dir",
        default=os.path.join(os.path.dirname(__file__), "..", "data"),
        help="Path to the data directory (default: ./data)",
    )
    parser.add_argument(
        "--email",
        default="local@praxys.dev",
        help="Email for the migrated user account",
    )
    args = parser.parse_args()

    migrate(os.path.abspath(args.data_dir), args.email)


if __name__ == "__main__":
    main()
