"""Tests for sync scheduler frequency guardrails."""

import pytest

from db.sync_scheduler import (
    ALLOWED_SYNC_INTERVAL_HOURS,
    DEFAULT_SYNC_INTERVAL_HOURS,
    get_user_sync_interval_hours,
    normalize_sync_interval_hours,
)


@pytest.mark.parametrize("hours", ALLOWED_SYNC_INTERVAL_HOURS)
def test_normalize_sync_interval_hours_allows_guardrails(hours: int) -> None:
    """Allowed sync interval options should be accepted."""
    assert normalize_sync_interval_hours(hours) == hours


@pytest.mark.parametrize("hours", [1, 3, 4, 8, 48, "fast", None])
def test_normalize_sync_interval_hours_rejects_invalid_values(hours: object) -> None:
    """Invalid sync intervals should be rejected."""
    with pytest.raises(ValueError):
        normalize_sync_interval_hours(hours)


@pytest.mark.parametrize(
    "source_options,expected",
    [
        ({}, DEFAULT_SYNC_INTERVAL_HOURS),
        ({"sync_interval_hours": 12}, 12),
        ({"sync_interval_hours": "24"}, 24),
        ({"sync_interval_hours": 2}, DEFAULT_SYNC_INTERVAL_HOURS),
        ({"sync_interval_hours": "bad"}, DEFAULT_SYNC_INTERVAL_HOURS),
        (None, DEFAULT_SYNC_INTERVAL_HOURS),
    ],
)
def test_get_user_sync_interval_hours_fallbacks(source_options: dict | None, expected: int) -> None:
    """Scheduler should safely fall back to default on missing/invalid config."""
    assert get_user_sync_interval_hours(source_options) == expected
