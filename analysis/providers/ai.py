"""AI plan provider — reads AI-generated training plans from CSV."""
import csv
import os
from datetime import date

import pandas as pd

from analysis.providers.base import PlanProvider
from analysis.providers import register_plan

# The 6 structured columns before the free-text description.
_PLAN_FIXED_COLS = [
    "date", "workout_type", "planned_duration_min",
    "planned_distance_km", "target_power_min", "target_power_max",
]


def _read_ai_plan_csv(path: str) -> pd.DataFrame:
    """Read an AI-generated plan CSV, tolerating unquoted commas in descriptions.

    AI models sometimes write CSV descriptions containing commas without
    proper quoting.  We handle this by treating everything after the 6th
    comma as the ``workout_description`` column.
    """
    rows: list[dict] = []
    with open(path, encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return pd.DataFrame()
        n_fixed = len(_PLAN_FIXED_COLS)
        for fields in reader:
            if len(fields) < n_fixed:
                continue
            row = {col: fields[i] for i, col in enumerate(_PLAN_FIXED_COLS)}
            # Rejoin any overflow fields into the description
            row["workout_description"] = ",".join(fields[n_fixed:]) if len(fields) > n_fixed else ""
            rows.append(row)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


class AiPlanProvider(PlanProvider):
    """Load AI-generated training plan from data/ai/training_plan.csv."""

    name = "ai"

    def load_plan(
        self, data_dir: str, since: date | None = None
    ) -> pd.DataFrame:
        csv_path = os.path.join(data_dir, "ai", "training_plan.csv")
        if not os.path.exists(csv_path):
            return pd.DataFrame()
        # AI-generated CSVs often have unquoted commas in the free-text
        # workout_description column.  We parse with Python's csv module
        # which handles this more reliably, then rejoin overflow fields
        # into the description column.
        try:
            df = _read_ai_plan_csv(csv_path)
        except Exception:
            return pd.DataFrame()
        if "date" in df.columns:
            df["date"] = pd.to_datetime(
                df["date"], format="%Y-%m-%d", errors="coerce",
            ).dt.date
            df = df.dropna(subset=["date"])
        if since and not df.empty and "date" in df.columns:
            df = df[df["date"] >= since]
        return df


register_plan("ai", AiPlanProvider)
