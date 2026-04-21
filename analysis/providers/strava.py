"""Strava provider — activity data from Strava sync exports."""

import os
from datetime import date

import pandas as pd

from analysis.data_loader import _read_csv_safe
from analysis.providers import register_activity
from analysis.providers.base import ActivityProvider


class StravaActivityProvider(ActivityProvider):
    """Load Strava activities and lap splits from CSV when using file mode."""

    name = "strava"

    def load_activities(
        self, data_dir: str, since: date | None = None
    ) -> pd.DataFrame:
        df = _read_csv_safe(os.path.join(data_dir, "strava", "activities.csv"))
        if since and not df.empty and "date" in df.columns:
            df = df[df["date"] >= since]
        return df

    def load_splits(
        self, data_dir: str, activity_ids: list[str] | None = None
    ) -> pd.DataFrame:
        df = _read_csv_safe(os.path.join(data_dir, "strava", "activity_splits.csv"))
        if activity_ids and not df.empty and "activity_id" in df.columns:
            df = df[df["activity_id"].astype(str).isin(activity_ids)]
        return df


register_activity("strava", StravaActivityProvider)
