"""Garmin provider — activities, splits, recovery, fitness (with thresholds)."""
import os
from datetime import date

import pandas as pd

from analysis.data_loader import _read_csv_safe
from analysis.providers.base import ActivityProvider, RecoveryProvider, FitnessProvider
from analysis.providers.models import ThresholdEstimate
from analysis.providers import register_activity, register_recovery, register_fitness


class GarminActivityProvider(ActivityProvider):
    """Load Garmin activity and split data from CSV."""

    name = "garmin"

    def load_activities(
        self, data_dir: str, since: date | None = None
    ) -> pd.DataFrame:
        df = _read_csv_safe(os.path.join(data_dir, "garmin", "activities.csv"))
        if since and not df.empty and "date" in df.columns:
            df = df[df["date"] >= since]
        return df

    def load_splits(
        self, data_dir: str, activity_ids: list[str] | None = None
    ) -> pd.DataFrame:
        df = _read_csv_safe(
            os.path.join(data_dir, "garmin", "activity_splits.csv")
        )
        if activity_ids and not df.empty and "activity_id" in df.columns:
            df = df[df["activity_id"].astype(str).isin(activity_ids)]
        return df


class GarminRecoveryProvider(RecoveryProvider):
    """Load Garmin daily metrics (resting HR, training readiness) as recovery data."""

    name = "garmin"

    def load_recovery(
        self, data_dir: str, since: date | None = None
    ) -> pd.DataFrame:
        df = _read_csv_safe(
            os.path.join(data_dir, "garmin", "daily_metrics.csv")
        )
        if df.empty:
            return df
        # Map Garmin columns to canonical recovery columns
        rename = {"resting_hr": "resting_hr"}
        if "training_readiness" in df.columns:
            rename["training_readiness"] = "readiness_score"
        df = df.rename(columns=rename)
        if since and "date" in df.columns:
            df = df[df["date"] >= since]
        return df


class GarminFitnessProvider(FitnessProvider):
    """Load Garmin fitness metrics (VO2max, training status, LT) and detect thresholds."""

    name = "garmin"

    def load_fitness(
        self, data_dir: str, since: date | None = None
    ) -> pd.DataFrame:
        df = _read_csv_safe(
            os.path.join(data_dir, "garmin", "daily_metrics.csv")
        )
        if df.empty:
            return df
        # Keep fitness-relevant columns
        fitness_cols = ["date", "vo2max", "training_status", "training_readiness",
                        "lthr_bpm", "lt_pace_sec_km", "lt_power_watts", "resting_hr"]
        available = [c for c in fitness_cols if c in df.columns]
        df = df[available].copy()
        if since and "date" in df.columns:
            df = df[df["date"] >= since]
        return df

    def detect_thresholds(self, data_dir: str) -> ThresholdEstimate:
        result = ThresholdEstimate(source="auto")

        # Primary: use Garmin's lactate threshold data if available
        lt = _read_csv_safe(
            os.path.join(data_dir, "garmin", "lactate_threshold.csv")
        )
        if not lt.empty:
            latest = lt.sort_values("date").iloc[-1]
            if "lthr_bpm" in lt.columns:
                lthr = pd.to_numeric(pd.Series([latest.get("lthr_bpm")]), errors="coerce").iloc[0]
                if pd.notna(lthr) and lthr > 0:
                    result.lthr_bpm = float(lthr)
            if "lt_pace_sec_km" in lt.columns:
                pace = pd.to_numeric(pd.Series([latest.get("lt_pace_sec_km")]), errors="coerce").iloc[0]
                if pd.notna(pace) and pace > 0:
                    result.threshold_pace_sec_km = float(pace)
            result.detected_date = latest.get("date")

        # Get resting HR from daily metrics
        daily = _read_csv_safe(
            os.path.join(data_dir, "garmin", "daily_metrics.csv")
        )
        if not daily.empty and "resting_hr" in daily.columns:
            rhr = pd.to_numeric(daily["resting_hr"], errors="coerce").dropna()
            if not rhr.empty:
                result.rest_hr_bpm = float(rhr.iloc[-1])

        # Get max HR from recent activities (highest max_hr observed)
        activities = _read_csv_safe(
            os.path.join(data_dir, "garmin", "activities.csv")
        )
        if not activities.empty and "max_hr" in activities.columns:
            max_hrs = pd.to_numeric(activities["max_hr"], errors="coerce").dropna()
            if not max_hrs.empty:
                result.max_hr_bpm = float(max_hrs.max())
                # Fallback: estimate LTHR as ~89% of max HR if not from Garmin LT data
                if result.lthr_bpm is None:
                    result.lthr_bpm = round(result.max_hr_bpm * 0.89)

        if not daily.empty and result.detected_date is None:
            result.detected_date = daily.sort_values("date").iloc[-1].get("date")

        return result


# Register providers
register_activity("garmin", GarminActivityProvider)
register_recovery("garmin", GarminRecoveryProvider)
register_fitness("garmin", GarminFitnessProvider)
