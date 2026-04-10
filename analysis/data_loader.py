"""Load and merge CSV data from all sources."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from analysis.config import UserConfig


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
