"""Provider registry — maps provider names to implementations."""
from analysis.providers.base import (
    ActivityProvider,
    RecoveryProvider,
    FitnessProvider,
    PlanProvider,
)

_ACTIVITY_PROVIDERS: dict[str, type[ActivityProvider]] = {}
_RECOVERY_PROVIDERS: dict[str, type[RecoveryProvider]] = {}
_FITNESS_PROVIDERS: dict[str, type[FitnessProvider]] = {}
_PLAN_PROVIDERS: dict[str, type[PlanProvider]] = {}


def register_activity(name: str, cls: type[ActivityProvider]) -> None:
    _ACTIVITY_PROVIDERS[name] = cls


def register_recovery(name: str, cls: type[RecoveryProvider]) -> None:
    _RECOVERY_PROVIDERS[name] = cls


def register_fitness(name: str, cls: type[FitnessProvider]) -> None:
    _FITNESS_PROVIDERS[name] = cls


def register_plan(name: str, cls: type[PlanProvider]) -> None:
    _PLAN_PROVIDERS[name] = cls


def get_activity_provider(name: str) -> ActivityProvider:
    _ensure_registered()
    return _ACTIVITY_PROVIDERS[name]()


def get_recovery_provider(name: str) -> RecoveryProvider:
    _ensure_registered()
    return _RECOVERY_PROVIDERS[name]()


def get_fitness_provider(name: str) -> FitnessProvider:
    _ensure_registered()
    return _FITNESS_PROVIDERS[name]()


def get_plan_provider(name: str) -> PlanProvider:
    _ensure_registered()
    return _PLAN_PROVIDERS[name]()


def available_providers() -> dict[str, list[str]]:
    """Return dict of category -> list of registered provider names."""
    _ensure_registered()
    return {
        "activities": list(_ACTIVITY_PROVIDERS.keys()),
        "recovery": list(_RECOVERY_PROVIDERS.keys()),
        "fitness": list(_FITNESS_PROVIDERS.keys()),
        "plan": list(_PLAN_PROVIDERS.keys()),
    }


_registered = False


def _ensure_registered() -> None:
    """Lazily import provider modules to trigger registration."""
    global _registered
    if _registered:
        return
    _registered = True
    # Import triggers register_*() calls at module level
    import analysis.providers.garmin  # noqa: F401
    import analysis.providers.stryd  # noqa: F401
    import analysis.providers.oura  # noqa: F401
    import analysis.providers.ai  # noqa: F401
