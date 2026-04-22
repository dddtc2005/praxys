"""intervals.icu provider — thin registry stub.

Runtime DB mode reads from the unified ``activities`` / ``recovery_data`` /
``fitness_data`` tables via ``analysis.data_loader.load_data_from_db``. This
provider exists for CSV-mode parity and registry symmetry with other
platforms. It returns empty DataFrames when no CSV is present (the expected
state in production).
"""
import os
from datetime import date

import pandas as pd

from analysis.data_loader import _read_csv_safe
from analysis.providers import register_activity
from analysis.providers.base import ActivityProvider


class IntervalsIcuActivityProvider(ActivityProvider):
    """Load intervals.icu activities and splits from CSV when using file mode."""

    name = "intervals_icu"

    def load_activities(
        self, data_dir: str, since: date | None = None
    ) -> pd.DataFrame:
        df = _read_csv_safe(
            os.path.join(data_dir, "intervals_icu", "activities.csv")
        )
        if since and not df.empty and "date" in df.columns:
            df = df[df["date"] >= since]
        return df

    def load_splits(
        self, data_dir: str, activity_ids: list[str] | None = None
    ) -> pd.DataFrame:
        df = _read_csv_safe(
            os.path.join(data_dir, "intervals_icu", "activity_splits.csv")
        )
        if activity_ids and not df.empty and "activity_id" in df.columns:
            df = df[df["activity_id"].astype(str).isin(activity_ids)]
        return df


register_activity("intervals_icu", IntervalsIcuActivityProvider)
