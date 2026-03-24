"""Abstract base classes for data providers."""
from abc import ABC, abstractmethod
from datetime import date

import pandas as pd

from analysis.providers.models import ThresholdEstimate


class ActivityProvider(ABC):
    """Provides activity and split data from a platform."""

    name: str

    @abstractmethod
    def load_activities(
        self, data_dir: str, since: date | None = None
    ) -> pd.DataFrame:
        """Return DataFrame with canonical Activity columns."""
        ...

    @abstractmethod
    def load_splits(
        self, data_dir: str, activity_ids: list[str] | None = None
    ) -> pd.DataFrame:
        """Return DataFrame with canonical Split columns."""
        ...


class RecoveryProvider(ABC):
    """Provides daily recovery data (sleep, HRV, readiness)."""

    name: str

    @abstractmethod
    def load_recovery(
        self, data_dir: str, since: date | None = None
    ) -> pd.DataFrame:
        """Return DataFrame with canonical Recovery columns."""
        ...


class FitnessProvider(ABC):
    """Provides fitness metrics (VO2max, training status, CP, LTHR).

    Also contributes threshold estimates — each fitness provider can
    return the thresholds it knows about (Stryd -> CP, Garmin -> LTHR).
    """

    name: str

    @abstractmethod
    def load_fitness(
        self, data_dir: str, since: date | None = None
    ) -> pd.DataFrame:
        """Return DataFrame with canonical Fitness columns."""
        ...

    def detect_thresholds(self, data_dir: str) -> ThresholdEstimate:
        """Return latest auto-detected thresholds.

        Default returns empty estimate. Override in subclasses that can
        detect thresholds (e.g., Stryd -> CP, Garmin -> LTHR).
        """
        return ThresholdEstimate()


class PlanProvider(ABC):
    """Provides planned workout data."""

    name: str

    @abstractmethod
    def load_plan(
        self, data_dir: str, since: date | None = None
    ) -> pd.DataFrame:
        """Return DataFrame with canonical PlannedWorkout columns."""
        ...
