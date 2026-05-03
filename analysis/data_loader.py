"""Load and merge CSV data from all sources.

Supports both file-based CSV loading (original) and database loading
via SQLAlchemy for the multi-user deployable architecture.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from analysis.config import UserConfig
    from sqlalchemy.orm import Session


# Required columns per CSV schema key.  Missing columns are logged as warnings
# but do not block loading — downstream code handles NaN/missing gracefully.
REQUIRED_COLUMNS: dict[str, list[str]] = {
    "activities": ["date", "distance_km", "duration_sec"],
    "splits": ["activity_id", "split_num"],
    "daily_metrics": ["date"],
    "power_data": ["date", "avg_power"],
    "training_plan": ["date"],
    "sleep": ["date"],
    "readiness": ["date"],
}


def discover_activity_types(
    connections: list[str], data_dir: str
) -> dict[str, list[str]]:
    """Return distinct activity_type values found in each provider's activities CSV.

    Reads each connected provider's activities CSV and extracts the unique
    ``activity_type`` column values.  Providers whose CSV is missing or lacks
    the column are returned with an empty list.

    Example return::

        {"garmin": ["running", "cycling", "hiking"], "stryd": ["running"]}
    """
    # Map provider name -> path to its activities CSV
    provider_csv: dict[str, str] = {
        "garmin": os.path.join(data_dir, "garmin", "activities.csv"),
        "stryd": os.path.join(data_dir, "stryd", "power_data.csv"),
        "coros": os.path.join(data_dir, "coros", "activities.csv"),
    }

    result: dict[str, list[str]] = {}
    for provider in connections:
        csv_path = provider_csv.get(provider)
        if csv_path is None:
            result[provider] = []
            continue
        df = _read_csv_safe(csv_path)
        if df.empty or "activity_type" not in df.columns:
            result[provider] = []
            continue
        types = sorted(
            df["activity_type"]
            .replace("", pd.NA)
            .dropna()
            .unique()
            .tolist()
        )
        result[provider] = [str(t) for t in types]
    return result


def _read_csv_safe(path: str, schema_key: str | None = None) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path)
    if schema_key and schema_key in REQUIRED_COLUMNS:
        missing = set(REQUIRED_COLUMNS[schema_key]) - set(df.columns)
        if missing:
            logger.warning("%s missing required columns: %s", path, missing)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def load_all_data(data_dir: str) -> dict[str, pd.DataFrame]:
    return {
        "garmin_activities": _read_csv_safe(os.path.join(data_dir, "garmin", "activities.csv"), "activities"),
        "garmin_splits": _read_csv_safe(os.path.join(data_dir, "garmin", "activity_splits.csv"), "splits"),
        "garmin_daily": _read_csv_safe(os.path.join(data_dir, "garmin", "daily_metrics.csv"), "daily_metrics"),
        "stryd_power": _read_csv_safe(os.path.join(data_dir, "stryd", "power_data.csv"), "power_data"),
        "stryd_plan": _read_csv_safe(os.path.join(data_dir, "stryd", "training_plan.csv"), "training_plan"),
        "oura_sleep": _read_csv_safe(os.path.join(data_dir, "oura", "sleep.csv"), "sleep"),
        "oura_readiness": _read_csv_safe(os.path.join(data_dir, "oura", "readiness.csv"), "readiness"),
    }


def _parse_time(t: str) -> datetime | None:
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"]:
        try:
            return datetime.strptime(t.replace("+00:00", "Z"), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def match_activities(garmin: pd.DataFrame, stryd: pd.DataFrame, window_minutes: int = 5) -> pd.DataFrame:
    """Merge Garmin and Stryd activity data by date.

    Primary match is by date (avoids Garmin-local vs Stryd-UTC timezone issues).
    When multiple activities share a date, falls back to timestamp proximity.
    """
    if garmin.empty:
        return stryd.copy() if not stryd.empty else garmin
    if stryd.empty:
        return garmin

    garmin = garmin.copy()
    stryd = stryd.copy()

    # Only add columns that are NEW — don't overwrite existing Garmin data
    skip = {"date", "start_time"}
    new_cols = [c for c in stryd.columns if c not in garmin.columns and c not in skip]
    shared_cols = [c for c in stryd.columns if c in garmin.columns and c not in skip]
    for col in new_cols:
        garmin[col] = pd.NA

    used_stryd = set()

    for i, g_row in garmin.iterrows():
        g_date = g_row["date"]
        # Find Stryd rows on the same date
        candidates = [(j, s_row) for j, s_row in stryd.iterrows()
                       if j not in used_stryd and s_row["date"] == g_date]

        if not candidates:
            continue

        if len(candidates) == 1:
            best_j = candidates[0][0]
        else:
            # Multiple activities on same day — use timestamp proximity
            g_time = _parse_time(str(g_row.get("start_time", "")))
            best_j = None
            best_diff = timedelta(hours=24)
            for j, s_row in candidates:
                s_time = _parse_time(str(s_row.get("start_time", "")))
                if g_time and s_time:
                    diff = abs(g_time.replace(tzinfo=None) - s_time.replace(tzinfo=None))
                    if diff < best_diff:
                        best_diff = diff
                        best_j = j
            if best_j is None:
                best_j = candidates[0][0]

        used_stryd.add(best_j)
        # Fill new columns (Stryd-only data like rss, cp_estimate, oscillation)
        for col in new_cols:
            garmin.at[i, col] = stryd.at[best_j, col]
        # For shared columns, prefer Stryd value if present (e.g., more accurate power)
        for col in shared_cols:
            stryd_val = stryd.at[best_j, col]
            if pd.notna(stryd_val):
                garmin.at[i, col] = stryd_val

    return garmin


# ---------------------------------------------------------------------------
# Provider-based loading (uses connections + preferences model)
# ---------------------------------------------------------------------------


def load_data(config: UserConfig, data_dir: str) -> dict[str, pd.DataFrame]:
    """Load data from configured providers, returning canonical DataFrames.

    Returns dict with keys: activities, splits, recovery, fitness, plan.
    The activities DataFrame is already merged with secondary sources
    (e.g. Stryd power overlay on Garmin activities).
    Fitness is auto-merged from all connected fitness providers.
    """
    from analysis.config import PLATFORM_CAPABILITIES
    from analysis.providers import (
        get_activity_provider,
        get_recovery_provider,
        get_fitness_provider,
        get_plan_provider,
    )

    connections = config.connections
    activity_source = config.preferences.get("activities", "garmin")
    recovery_source = config.preferences.get("recovery", "oura")
    plan_source = config.preferences.get("plan", "")

    # --- Activities: primary + enrichment from other connected sources ---
    activity_provider = get_activity_provider(activity_source)
    activities = activity_provider.load_activities(data_dir)
    splits = activity_provider.load_splits(data_dir)

    # Enrich with other connected activity providers
    for conn in connections:
        if conn == activity_source:
            continue
        caps = PLATFORM_CAPABILITIES.get(conn, {})
        if not caps.get("activities"):
            continue
        try:
            secondary = get_activity_provider(conn)
        except KeyError:
            continue  # Provider not registered
        try:
            secondary_data = secondary.load_activities(data_dir)
            if not secondary_data.empty and not activities.empty:
                activities = match_activities(activities, secondary_data)
        except Exception as e:
            logger.warning("Activity enrichment from %s failed: %s", conn, e)

    # --- Recovery: single preferred source ---
    try:
        recovery_provider = get_recovery_provider(recovery_source)
        recovery = recovery_provider.load_recovery(data_dir)
    except KeyError:
        recovery = pd.DataFrame()

    # --- Fitness: auto-merge from ALL connected fitness providers ---
    fitness_frames = []
    for conn in connections:
        caps = PLATFORM_CAPABILITIES.get(conn, {})
        if not caps.get("fitness"):
            continue
        try:
            fp = get_fitness_provider(conn)
        except KeyError:
            continue  # Provider not registered
        try:
            f_data = fp.load_fitness(data_dir)
            if not f_data.empty:
                fitness_frames.append(f_data)
        except Exception as e:
            logger.warning("Fitness data from %s failed: %s", conn, e)

    if fitness_frames:
        # Merge all fitness DataFrames on date (outer join, first non-null wins)
        fitness = fitness_frames[0]
        for extra in fitness_frames[1:]:
            fitness = fitness.merge(extra, on="date", how="outer", suffixes=("", "_dup"))
            # For duplicate columns, keep first non-null
            dup_cols = [c for c in fitness.columns if c.endswith("_dup")]
            for dc in dup_cols:
                orig = dc.removesuffix("_dup")
                if orig in fitness.columns:
                    fitness[orig] = fitness[orig].fillna(fitness[dc])
                fitness = fitness.drop(columns=[dc])
    else:
        fitness = pd.DataFrame()

    # --- Plan: single preferred source ---
    plan = pd.DataFrame()
    if plan_source:
        try:
            plan_provider = get_plan_provider(plan_source)
            plan = plan_provider.load_plan(data_dir)
        except KeyError:
            pass

    # Post-processing: sort, deduplicate, compute numeric pace
    activities = _clean_activities(activities)
    activities = _ensure_numeric_pace(activities)
    splits = _ensure_numeric_pace(splits)

    return {
        "activities": activities,
        "splits": splits,
        "recovery": recovery,
        "fitness": fitness,
        "plan": plan,
    }


def _clean_activities(df: pd.DataFrame) -> pd.DataFrame:
    """Sort by date and remove true duplicates (same date + distance + duration)."""
    if df.empty or "date" not in df.columns:
        return df
    df = df.copy()
    # Sort by date
    df = df.sort_values("date").reset_index(drop=True)
    # Drop true duplicates: same date + distance + duration (scraped twice)
    dedup_cols = ["date"]
    if "distance_km" in df.columns:
        dedup_cols.append("distance_km")
    if "duration_sec" in df.columns:
        dedup_cols.append("duration_sec")
    df = df.drop_duplicates(subset=dedup_cols, keep="first")
    return df.reset_index(drop=True)


def _ensure_numeric_pace(df: pd.DataFrame) -> pd.DataFrame:
    """Add avg_pace_sec_km column if it doesn't exist, computed from distance/duration."""
    if df.empty:
        return df
    if "avg_pace_sec_km" not in df.columns:
        if "distance_km" in df.columns and "duration_sec" in df.columns:
            dist = pd.to_numeric(df["distance_km"], errors="coerce")
            dur = pd.to_numeric(df["duration_sec"], errors="coerce")
            df = df.copy()
            df["avg_pace_sec_km"] = (dur / dist).where(dist > 0)
    return df


# ---------------------------------------------------------------------------
# Database-based loading (multi-user deployable architecture)
# ---------------------------------------------------------------------------


def load_data_from_db(user_id: str, db: Session) -> dict[str, pd.DataFrame]:
    """Load data from database for a specific user.

    Returns the same dict structure as load_data():
    {activities, splits, recovery, fitness, plan}.
    """
    activities = pd.read_sql(
        "SELECT * FROM activities WHERE user_id = :uid ORDER BY date",
        db.bind,
        params={"uid": user_id},
        parse_dates=["date"],
    )
    if "date" in activities.columns and not activities.empty:
        activities["date"] = pd.to_datetime(activities["date"]).dt.date

    splits = pd.read_sql(
        "SELECT * FROM activity_splits WHERE user_id = :uid",
        db.bind,
        params={"uid": user_id},
    )

    # Recovery: reconstruct from recovery_data table
    recovery = pd.read_sql(
        "SELECT * FROM recovery_data WHERE user_id = :uid ORDER BY date",
        db.bind,
        params={"uid": user_id},
        parse_dates=["date"],
    )
    if "date" in recovery.columns and not recovery.empty:
        recovery["date"] = pd.to_datetime(recovery["date"]).dt.date

    # Fitness: pivot fitness_data rows into wide columns
    fitness_raw = pd.read_sql(
        "SELECT date, metric_type, value, value_str "
        "FROM fitness_data WHERE user_id = :uid ORDER BY date",
        db.bind,
        params={"uid": user_id},
        parse_dates=["date"],
    )
    fitness = _pivot_fitness(fitness_raw)

    # Plan
    plan = pd.read_sql(
        "SELECT * FROM training_plans WHERE user_id = :uid ORDER BY date",
        db.bind,
        params={"uid": user_id},
        parse_dates=["date"],
    )
    if "date" in plan.columns and not plan.empty:
        plan["date"] = pd.to_datetime(plan["date"]).dt.date

    # Post-processing (same as CSV path)
    activities = _clean_activities(activities)
    activities = _ensure_numeric_pace(activities)
    splits = _ensure_numeric_pace(splits)

    return {
        "activities": activities,
        "splits": splits,
        "recovery": recovery,
        "fitness": fitness,
        "plan": plan,
    }


def load_activity_samples(
    user_id: str,
    db,
    activity_ids: list[str] | None = None,
) -> pd.DataFrame:
    """Load per-second stream samples from activity_samples for analysis.

    Returns a DataFrame with columns: activity_id, t_sec, power_watts,
    hr_bpm, pace_sec_km, source. Columns not populated by a given connector
    will be present but NaN.

    If activity_ids is provided, only samples for those activities are
    returned. The filter is pushed into SQL (``AND activity_id IN (...)``)
    so users with months of streamed history don't pay to load every row
    just to discard everything outside the recent window in Python — the
    /api/training cold path is bound by this load on a fresh cache.

    Passing an empty list returns an empty DataFrame without touching the
    DB. Passing ``None`` preserves the legacy "all-history" behavior for
    callers that need it (e.g. backfill / one-off scripts).
    """
    base_sql = (
        "SELECT activity_id, t_sec, power_watts, hr_bpm, pace_sec_km, source "
        "FROM activity_samples WHERE user_id = :uid"
    )
    params: dict[str, object] = {"uid": user_id}

    if activity_ids is None:
        return pd.read_sql(base_sql, db.bind, params=params)

    if not activity_ids:
        return pd.DataFrame(
            columns=[
                "activity_id", "t_sec", "power_watts",
                "hr_bpm", "pace_sec_km", "source",
            ]
        )

    # Deduplicate as strings — DB stores activity_id as VARCHAR.
    unique_ids = list({str(a) for a in activity_ids})

    # Chunk under SQLite's default ~999 host-parameter limit. Realistic
    # callers stay well below this (e.g. 8 weeks of activities ≈ 30-50
    # ids), but the chunked path is a cheap belt for backfill / power
    # users with very long lookbacks.
    chunk_size = 500
    frames: list[pd.DataFrame] = []
    for start in range(0, len(unique_ids), chunk_size):
        chunk = unique_ids[start:start + chunk_size]
        placeholders = ",".join(f":a{i}" for i in range(len(chunk)))
        chunk_params = {**params, **{f"a{i}": v for i, v in enumerate(chunk)}}
        frames.append(
            pd.read_sql(
                f"{base_sql} AND activity_id IN ({placeholders})",
                db.bind,
                params=chunk_params,
            )
        )
    if not frames:
        return pd.DataFrame()
    if len(frames) == 1:
        return frames[0]
    return pd.concat(frames, ignore_index=True)


def _pivot_fitness(raw: pd.DataFrame) -> pd.DataFrame:
    """Pivot fitness_data rows into a wide DataFrame with one column per metric."""
    if raw.empty:
        return pd.DataFrame()
    raw = raw.copy()
    raw["date"] = pd.to_datetime(raw["date"]).dt.date
    # Use value for numeric, value_str for string metrics
    raw["final_value"] = raw["value"].fillna(raw["value_str"])
    pivoted = raw.pivot_table(
        index="date", columns="metric_type", values="final_value", aggfunc="first"
    )
    pivoted = pivoted.reset_index()
    # Convert numeric columns
    for col in pivoted.columns:
        if col not in ("date", "training_status"):
            pivoted[col] = pd.to_numeric(pivoted[col], errors="coerce")
    return pivoted
