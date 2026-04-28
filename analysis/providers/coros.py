"""COROS provider — activities, splits, recovery, fitness (VO2max, LTHR)."""
import os
from datetime import date

import pandas as pd

from analysis.data_loader import _read_csv_safe
from analysis.providers.base import ActivityProvider, RecoveryProvider, FitnessProvider
from analysis.providers.models import ThresholdEstimate
from analysis.providers import register_activity, register_recovery, register_fitness


class CorosActivityProvider(ActivityProvider):
    """Load COROS activity and split data from DB (via CSV-shaped loader)."""

    name = "coros"

    def load_activities(
        self, data_dir: str, since: date | None = None
    ) -> pd.DataFrame:
        df = _read_csv_safe(os.path.join(data_dir, "coros", "activities.csv"))
        if since and not df.empty and "date" in df.columns:
            df = df[df["date"] >= since]
        return df

    def load_splits(
        self, data_dir: str, activity_ids: list[str] | None = None
    ) -> pd.DataFrame:
        df = _read_csv_safe(
            os.path.join(data_dir, "coros", "activity_splits.csv")
        )
        if activity_ids and not df.empty and "activity_id" in df.columns:
            df = df[df["activity_id"].astype(str).isin(activity_ids)]
        return df


class CorosRecoveryProvider(RecoveryProvider):
    """Load COROS recovery data (HRV, resting HR) from daily metrics."""

    name = "coros"

    def load_recovery(
        self, data_dir: str, since: date | None = None
    ) -> pd.DataFrame:
        df = _read_csv_safe(
            os.path.join(data_dir, "coros", "daily_metrics.csv")
        )
        if df.empty:
            return df
        # Map COROS columns to canonical recovery columns
        rename = {"resting_hr": "resting_hr"}
        if "hrv_ms" in df.columns:
            rename["hrv_ms"] = "hrv_ms"
        df = df.rename(columns=rename)
        if since and "date" in df.columns:
            df = df[df["date"] >= since]
        return df


class CorosFitnessProvider(FitnessProvider):
    """Load COROS fitness metrics (VO2max, training load) and detect thresholds."""

    name = "coros"

    def load_fitness(
        self, data_dir: str, since: date | None = None
    ) -> pd.DataFrame:
        df = _read_csv_safe(
            os.path.join(data_dir, "coros", "daily_metrics.csv")
        )
        if df.empty:
            return df
        fitness_cols = ["date", "vo2max", "training_load", "resting_hr",
                        "lthr_bpm", "lt_pace_sec_km"]
        available = [c for c in fitness_cols if c in df.columns]
        df = df[available].copy()
        if since and "date" in df.columns:
            df = df[df["date"] >= since]
        return df

    def detect_thresholds(self, data_dir: str) -> ThresholdEstimate:
        result = ThresholdEstimate(source="auto")

        # VO2max / LTHR from daily metrics
        daily = _read_csv_safe(
            os.path.join(data_dir, "coros", "daily_metrics.csv")
        )

        if not daily.empty and "resting_hr" in daily.columns:
            rhr = pd.to_numeric(daily["resting_hr"], errors="coerce").dropna()
            if not rhr.empty:
                result.rest_hr_bpm = float(rhr.iloc[-1])

        # Max HR from activities
        activities = _read_csv_safe(
            os.path.join(data_dir, "coros", "activities.csv")
        )
        if not activities.empty and "max_hr" in activities.columns:
            max_hrs = pd.to_numeric(activities["max_hr"], errors="coerce").dropna()
            if not max_hrs.empty:
                result.max_hr_bpm = float(max_hrs.max())
                if result.lthr_bpm is None:
                    result.lthr_bpm = round(result.max_hr_bpm * 0.89)

        if not daily.empty:
            result.detected_date = daily.sort_values("date").iloc[-1].get("date")

        return result


# Register providers
register_activity("coros", CorosActivityProvider)
register_recovery("coros", CorosRecoveryProvider)
register_fitness("coros", CorosFitnessProvider)
