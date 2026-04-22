"""API route + scheduler integration for intervals.icu."""
from unittest.mock import patch

import pytest


def test_intervals_icu_is_in_default_sources():
    from api.routes.sync import _DEFAULT_SOURCES
    assert "intervals_icu" in _DEFAULT_SOURCES


def test_sync_intervals_icu_handler_exists():
    """The internal handler used by both scheduler and manual sync must exist
    under the name the scheduler imports (_sync_intervals_icu)."""
    from api.routes.sync import _sync_intervals_icu
    assert callable(_sync_intervals_icu)


@patch("api.routes.sync.intervals_icu_sync")
def test_sync_intervals_icu_handler_invokes_sync_all(mock_mod):
    """_sync_intervals_icu must call sync_all with correct kwargs and
    return a counts dict derived from SyncResult."""
    from api.routes.sync import _sync_intervals_icu
    from sync.intervals_icu_sync import SyncResult

    mock_mod.sync_all.return_value = SyncResult(
        activities_written=5, splits_written=12,
        wellness_written=7, thresholds_written=4,
    )
    creds = {"athlete_id": "i1", "api_key": "k"}

    counts = _sync_intervals_icu("u1", creds, None, db=None)

    mock_mod.sync_all.assert_called_once()
    call = mock_mod.sync_all.call_args
    assert call.kwargs["user_id"] == "u1"
    assert call.kwargs["credentials"] == creds
    assert "since" in call.kwargs

    # Counts dict exposes each field from SyncResult.
    assert counts["activities"] == 5
    assert counts["splits"] == 12
    assert counts["recovery"] == 7
    assert counts["fitness"] == 4


@patch("api.routes.sync.intervals_icu_sync")
def test_sync_intervals_icu_honors_from_date(mock_mod):
    """When from_date is supplied, it overrides the default 180-day window."""
    from datetime import date
    from api.routes.sync import _sync_intervals_icu
    from sync.intervals_icu_sync import SyncResult

    mock_mod.sync_all.return_value = SyncResult()
    _sync_intervals_icu("u1", {"athlete_id":"i1","api_key":"k"}, "2025-01-15", db=None)

    call = mock_mod.sync_all.call_args
    assert call.kwargs["since"] == date(2025, 1, 15)


def test_scheduler_handles_intervals_icu_platform():
    """Confirm the scheduler's dispatch doesn't choke on platform=intervals_icu
    — it should route to _sync_connection which dispatches to intervals_icu_sync."""
    # Not a behavior test on the scheduler's elif branch per se (that's
    # unit-tested via test_scheduler_dispatches_intervals_icu below), just
    # confirms the imports wire correctly.
    from db.sync_scheduler import _sync_connection
    assert callable(_sync_connection)


@patch("sync.intervals_icu_sync.sync_all")
def test_scheduler_dispatches_intervals_icu(mock_sync_all):
    """_sync_connection with platform='intervals_icu' calls sync_all via the
    api.routes.sync._sync_intervals_icu handler."""
    from datetime import date
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as SASession
    from db.models import Base, User, UserConnection
    from db.crypto import get_vault
    from sync.intervals_icu_sync import SyncResult

    # Build a minimal in-memory DB with a user + connection.
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with SASession(engine) as db:
        db.add(User(id="u1", email="t@e.com", hashed_password="x"))
        db.commit()

        vault = get_vault()
        import json
        encrypted, wrapped = vault.encrypt(json.dumps({"athlete_id": "i1", "api_key": "k"}))
        db.add(UserConnection(
            user_id="u1", platform="intervals_icu",
            encrypted_credentials=encrypted, wrapped_dek=wrapped,
            status="connected",
        ))
        db.commit()

        mock_sync_all.return_value = SyncResult(activities_written=3)

        from db.sync_scheduler import _sync_connection
        _sync_connection("u1", "intervals_icu", db)

        mock_sync_all.assert_called_once()
        call = mock_sync_all.call_args
        assert call.kwargs["user_id"] == "u1"
        assert call.kwargs["credentials"] == {"athlete_id": "i1", "api_key": "k"}
