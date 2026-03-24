"""AI plan provider — reads AI-generated training plans from CSV."""
import os
from datetime import date

import pandas as pd

from analysis.data_loader import _read_csv_safe
from analysis.providers.base import PlanProvider
from analysis.providers import register_plan


class AiPlanProvider(PlanProvider):
    """Load AI-generated training plan from data/ai/training_plan.csv."""

    name = "ai"

    def load_plan(
        self, data_dir: str, since: date | None = None
    ) -> pd.DataFrame:
        csv_path = os.path.join(data_dir, "ai", "training_plan.csv")
        df = _read_csv_safe(csv_path)
        if since and not df.empty and "date" in df.columns:
            df = df[df["date"] >= since]
        return df


register_plan("ai", AiPlanProvider)
