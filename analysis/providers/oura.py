"""Oura provider — sleep and readiness recovery data."""
import os
from datetime import date

import pandas as pd

from analysis.data_loader import _read_csv_safe
from analysis.providers.base import RecoveryProvider
from analysis.providers import register_recovery


class OuraRecoveryProvider(RecoveryProvider):
    """Load Oura sleep and readiness data, merged into a single recovery DataFrame."""

    name = "oura"

    def load_recovery(
        self, data_dir: str, since: date | None = None
    ) -> pd.DataFrame:
        sleep = _read_csv_safe(os.path.join(data_dir, "oura", "sleep.csv"))
        readiness = _read_csv_safe(
            os.path.join(data_dir, "oura", "readiness.csv")
        )

        if sleep.empty and readiness.empty:
            return pd.DataFrame()

        # Merge sleep + readiness on date
        if not sleep.empty and not readiness.empty:
            df = readiness.merge(sleep, on="date", how="outer", suffixes=("", "_sleep"))
        elif not readiness.empty:
            df = readiness
        else:
            df = sleep

        if since and "date" in df.columns:
            df = df[df["date"] >= since]

        return df


# Register provider
register_recovery("oura", OuraRecoveryProvider)
