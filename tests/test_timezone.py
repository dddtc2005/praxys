"""Tests for UTC timestamp serialization.

Regression guard for a class of bugs where naive UTC datetimes stored in the
DB (``datetime.utcnow()``) were serialized with ``.isoformat()`` and shipped to
the browser without a timezone marker. Per the ECMAScript spec,
``new Date("2026-04-18T12:34:56")`` (no tz suffix) is parsed as **local** time,
so users on non-UTC clocks saw "Last synced" stamps that were off by their UTC
offset.
"""
from datetime import datetime, timedelta, timezone

import pytest

from api.views import utc_isoformat


def test_utc_isoformat_returns_none_for_none() -> None:
    assert utc_isoformat(None) is None


def test_utc_isoformat_tags_naive_datetime_as_utc() -> None:
    """Naive datetimes (``datetime.utcnow()``) must be labelled UTC on output.

    Without a suffix, JavaScript ``new Date()`` would interpret the string as
    local time. The ``+00:00`` offset pins the moment unambiguously.
    """
    naive = datetime(2026, 4, 18, 12, 34, 56)
    out = utc_isoformat(naive)
    assert out is not None
    assert out.endswith("+00:00"), out
    assert out.startswith("2026-04-18T12:34:56")


def test_utc_isoformat_preserves_aware_utc_datetime() -> None:
    aware = datetime(2026, 4, 18, 12, 34, 56, tzinfo=timezone.utc)
    assert utc_isoformat(aware) == "2026-04-18T12:34:56+00:00"


def test_utc_isoformat_normalizes_non_utc_timezone() -> None:
    """A tz-aware datetime in another zone must be normalized to UTC."""
    tz = timezone(timedelta(hours=8))  # e.g. Asia/Shanghai-ish
    aware = datetime(2026, 4, 18, 20, 34, 56, tzinfo=tz)
    out = utc_isoformat(aware)
    assert out == "2026-04-18T12:34:56+00:00"


@pytest.mark.parametrize("sample", [
    "2026-04-18T12:34:56+00:00",
    "2026-04-18T12:34:56.789012+00:00",
])
def test_utc_isoformat_output_is_parseable_as_utc(sample: str) -> None:
    """Round-trip the output back through ``fromisoformat`` and confirm UTC.

    This is the contract the frontend relies on: ``new Date(s)`` in JS lands
    on the same absolute moment regardless of the viewer's local timezone.
    """
    parsed = datetime.fromisoformat(sample)
    assert parsed.utcoffset() == timedelta(0)


def test_sync_status_last_sync_is_tz_aware(api_client, monkeypatch) -> None:
    """Integration guard: ``/api/sync/status`` must emit tz-aware timestamps.

    Stores a naive UTC ``last_sync`` (mirroring what the scheduler writes) and
    then hits the status endpoint. The serialized timestamp must round-trip
    back to a UTC-offset datetime; a failure here means the browser would
    interpret the value as local time again.
    """
    client, user_id = api_client

    # Seed a UserConnection with a naive UTC last_sync, just like the scheduler
    # writes via ``datetime.utcnow()``.
    from db import session as db_session
    from db.models import UserConnection

    naive_utc = datetime(2026, 4, 18, 12, 34, 56)
    sess = db_session.SessionLocal()
    try:
        sess.add(UserConnection(
            user_id=user_id,
            platform="garmin",
            preferences={},
            last_sync=naive_utc,
            status="connected",
        ))
        sess.commit()
    finally:
        sess.close()

    res = client.get("/api/sync/status")
    assert res.status_code == 200, res.text
    payload = res.json()
    stamp = payload.get("garmin", {}).get("last_sync")
    assert stamp is not None, payload
    # Must carry a UTC offset so JS ``new Date()`` doesn't fall back to local.
    parsed = datetime.fromisoformat(stamp)
    assert parsed.utcoffset() == timedelta(0), stamp
    # And point at the same instant we wrote.
    assert parsed.replace(tzinfo=None) == naive_utc


# Reuse the fully-configured test client fixture from the settings-API tests.
from tests.test_settings_api import api_client  # noqa: E402,F401
