"""Stryd provider — power overlay for activities, training plan, fitness (CP)."""
import os
from datetime import date

import pandas as pd

from analysis.data_loader import _read_csv_safe
from analysis.providers.base import ActivityProvider, FitnessProvider, PlanProvider
from analysis.providers.models import ThresholdEstimate
from analysis.providers import register_activity, register_fitness, register_plan


class StrydActivityProvider(ActivityProvider):
    """Load Stryd power data as an activity overlay (merged onto primary source)."""

    name = "stryd"

    def load_activities(
        self, data_dir: str, since: date | None = None
    ) -> pd.DataFrame:
        df = _read_csv_safe(os.path.join(data_dir, "stryd", "power_data.csv"))
        if since and not df.empty and "date" in df.columns:
            df = df[df["date"] >= since]
        return df

    def load_splits(
        self, data_dir: str, activity_ids: list[str] | None = None
    ) -> pd.DataFrame:
        # Stryd doesn't provide its own split data — Garmin CIQ does
        return pd.DataFrame()


class StrydFitnessProvider(FitnessProvider):
    """Load Stryd fitness data (CP estimates) and detect CP threshold."""

    name = "stryd"

    def load_fitness(
        self, data_dir: str, since: date | None = None
    ) -> pd.DataFrame:
        df = _read_csv_safe(os.path.join(data_dir, "stryd", "power_data.csv"))
        if df.empty:
            return df
        # Extract fitness-relevant columns from Stryd power data
        fitness_cols = ["date", "cp_estimate", "leg_spring_stiffness", "avg_oscillation", "avg_stride_length"]
        available = [c for c in fitness_cols if c in df.columns]
        df = df[available].copy()
        if since and "date" in df.columns:
            df = df[df["date"] >= since]
        return df

    def detect_thresholds(self, data_dir: str) -> ThresholdEstimate:
        df = _read_csv_safe(os.path.join(data_dir, "stryd", "power_data.csv"))
        if df.empty or "cp_estimate" not in df.columns:
            return ThresholdEstimate(source="auto")

        cp_vals = pd.to_numeric(df["cp_estimate"], errors="coerce").dropna()
        cp_vals = cp_vals[cp_vals > 0]
        if cp_vals.empty:
            return ThresholdEstimate(source="auto")

        latest_idx = cp_vals.index[-1]
        return ThresholdEstimate(
            cp_watts=float(cp_vals.iloc[-1]),
            source="auto",
            detected_date=df.loc[latest_idx, "date"] if "date" in df.columns else None,
        )


class StrydPlanProvider(PlanProvider):
    """Load Stryd training plan from CSV."""

    name = "stryd"

    def load_plan(
        self, data_dir: str, since: date | None = None
    ) -> pd.DataFrame:
        df = _read_csv_safe(
            os.path.join(data_dir, "stryd", "training_plan.csv")
        )
        if since and not df.empty and "date" in df.columns:
            df = df[df["date"] >= since]
        return df


# Register providers
register_activity("stryd", StrydActivityProvider)
register_fitness("stryd", StrydFitnessProvider)
register_plan("stryd", StrydPlanProvider)
