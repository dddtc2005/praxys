"""Tests for the sync-failure backoff state machine.

Background — the 2026-04-25 Garmin lockout traced back to the scheduler
retrying failed connections every 10 min indefinitely. Repeated automated
SSO attempts from one Azure App Service IP escalated Garmin's bot
mitigation from a transient 429 to a persistent CAPTCHA flag, which
locked out four users until the connection-state machine learned to
back off (transient errors) and stop entirely (auth-required errors).

These tests cover the four pieces that together prevent a repeat:

1. ``backoff_seconds`` — exponential schedule capped at 24h.
2. ``classify_sync_failure`` — distinguishes terminal auth gates from
   transient connection errors so the scheduler can stop hammering the
   former without locking out the latter forever.
3. ``_record_sync_failure`` — writes the new status, counter, retry
   timestamp, and short error tag to the connection row.
4. ``_check_and_sync`` — actually skips backed-off / auth-required rows
   and clears state on a successful sync.
"""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def db_setup(monkeypatch):
    """Init a clean SQLite DB with one seeded user for the integration tests."""
    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    monkeypatch.setenv("DATA_DIR", tmpdir.name)
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "false")
    monkeypatch.setenv(
        "PRAXYS_LOCAL_ENCRYPTION_KEY",
        "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=",
    )

    from db import session as db_session
    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    from db.models import User

    user_id = "backoff-test-user"
    db = db_session.SessionLocal()
    try:
        db.add(User(id=user_id, email="backoff@example.com", hashed_password="x"))
        db.commit()
    finally:
        db.close()

    yield user_id, tmpdir


# ---------------------------------------------------------------------------
# backoff_seconds — pure math
# ---------------------------------------------------------------------------

def test_backoff_seconds_exponential_then_capped() -> None:
    """1h, 2h, 4h, 8h, 16h, then capped at 24h regardless of further failures."""
    from db.sync_scheduler import backoff_seconds, BACKOFF_MAX_SEC

    assert backoff_seconds(1) == 3600
    assert backoff_seconds(2) == 7200
    assert backoff_seconds(3) == 14400
    assert backoff_seconds(4) == 28800
    assert backoff_seconds(5) == 57600
    assert backoff_seconds(6) == BACKOFF_MAX_SEC  # 16h*2 = 32h → capped at 24h
    assert backoff_seconds(20) == BACKOFF_MAX_SEC


def test_backoff_seconds_treats_zero_as_first_failure() -> None:
    """The retry-state init value is 0; the formula must still produce 1h."""
    from db.sync_scheduler import backoff_seconds

    assert backoff_seconds(0) == 3600


# ---------------------------------------------------------------------------
# classify_sync_failure — pure logic
# ---------------------------------------------------------------------------

class _FakeAuthError(Exception):
    """Stand-in for garminconnect.GarminConnectAuthenticationError."""


# Class name has to match exactly — classification is name-based to avoid
# importing garminconnect from a pure-logic test.
_FakeAuthError.__name__ = "GarminConnectAuthenticationError"


def test_classify_authentication_error_is_terminal() -> None:
    """Wrong-password / JWT_WEB-fallthrough errors stop the scheduler entirely."""
    from db.sync_scheduler import classify_sync_failure

    status, terminal = classify_sync_failure(
        _FakeAuthError("401 Unauthorized (Invalid Username or Password)")
    )
    assert status == "auth_required"
    assert terminal is True


def test_classify_captcha_required_in_message_is_terminal() -> None:
    """CAPTCHA_REQUIRED can't be solved headlessly — stop and ask the user."""
    from db.sync_scheduler import classify_sync_failure

    # The library wraps the failing strategy's error in "All login strategies
    # exhausted: …" — the CAPTCHA marker has to survive that wrapping.
    err = RuntimeError(
        "All login strategies exhausted: Portal web login failed: "
        "{'responseStatus': {'type': 'CAPTCHA_REQUIRED'}, ...}"
    )
    status, terminal = classify_sync_failure(err)
    assert status == "auth_required"
    assert terminal is True


def test_classify_generic_connection_error_is_transient() -> None:
    """A 403 / 429 / network blip should retry under exponential backoff."""
    from db.sync_scheduler import classify_sync_failure

    err = RuntimeError("Portal login failed (non-JSON): HTTP 403")
    status, terminal = classify_sync_failure(err)
    assert status == "error"
    assert terminal is False


# ---------------------------------------------------------------------------
# _record_sync_failure — DB-level integration
# ---------------------------------------------------------------------------

def _make_connection(db, user_id: str, platform: str = "garmin"):
    from db.models import UserConnection

    conn = UserConnection(
        user_id=user_id,
        platform=platform,
        status="connected",
        consecutive_failures=0,
    )
    db.add(conn)
    db.commit()
    return conn


def test_record_failure_increments_counter_and_schedules_retry(db_setup) -> None:
    """First transient failure: counter=1, next_retry_at=+1h, status=error."""
    from db import session as db_session
    from db.sync_scheduler import _record_sync_failure
    from db.models import UserConnection

    user_id, _ = db_setup
    db = db_session.SessionLocal()
    try:
        conn = _make_connection(db, user_id)
        before = datetime.utcnow()

        _record_sync_failure(conn, RuntimeError("HTTP 403"), db)

        fresh = db.query(UserConnection).filter(
            UserConnection.id == conn.id,
        ).first()
        assert fresh.consecutive_failures == 1
        assert fresh.status == "error"
        assert fresh.next_retry_at is not None
        # ~1h, with a generous window for slow CI
        delta = (fresh.next_retry_at - before).total_seconds()
        assert 3500 <= delta <= 3700
        assert "HTTP 403" in (fresh.last_error or "")
    finally:
        db.close()


def test_record_failure_captcha_clears_next_retry_at(db_setup) -> None:
    """Terminal auth failures must NOT set next_retry_at — the scheduler
    skips on status alone, and a stale timestamp would be misleading in
    the UI."""
    from db import session as db_session
    from db.sync_scheduler import _record_sync_failure
    from db.models import UserConnection

    user_id, _ = db_setup
    db = db_session.SessionLocal()
    try:
        conn = _make_connection(db, user_id)
        # Pre-populate a stale retry timestamp from an earlier transient
        # failure to verify the terminal classification overwrites it.
        conn.next_retry_at = datetime.utcnow() + timedelta(hours=2)
        conn.consecutive_failures = 3
        db.commit()

        err = RuntimeError(
            "All login strategies exhausted: Portal web login failed: "
            "{'responseStatus': {'type': 'CAPTCHA_REQUIRED'}}"
        )
        _record_sync_failure(conn, err, db)

        fresh = db.query(UserConnection).filter(
            UserConnection.id == conn.id,
        ).first()
        assert fresh.status == "auth_required"
        assert fresh.next_retry_at is None
        assert fresh.consecutive_failures == 4
        assert "CAPTCHA_REQUIRED" in (fresh.last_error or "")
    finally:
        db.close()


def test_record_failure_consecutive_failures_grow(db_setup) -> None:
    """Each successive failure increments the counter and stretches the retry."""
    from db import session as db_session
    from db.sync_scheduler import _record_sync_failure, backoff_seconds
    from db.models import UserConnection

    user_id, _ = db_setup
    db = db_session.SessionLocal()
    try:
        conn = _make_connection(db, user_id)

        for expected_n in (1, 2, 3):
            before = datetime.utcnow()
            _record_sync_failure(conn, RuntimeError("transient"), db)
            fresh = db.query(UserConnection).filter(
                UserConnection.id == conn.id,
            ).first()
            assert fresh.consecutive_failures == expected_n
            expected_delay = backoff_seconds(expected_n)
            actual = (fresh.next_retry_at - before).total_seconds()
            # ±100s tolerance for slow CI runners
            assert abs(actual - expected_delay) < 100, (
                f"After {expected_n} failures expected ~{expected_delay}s, got {actual:.0f}s"
            )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# reset_connection_backoff — clear state on success / reconnect
# ---------------------------------------------------------------------------

def test_reset_clears_all_backoff_fields(db_setup) -> None:
    """Reset wipes counter, retry timestamp, and error tag in one shot."""
    from db import session as db_session
    from db.sync_scheduler import reset_connection_backoff

    user_id, _ = db_setup
    db = db_session.SessionLocal()
    try:
        conn = _make_connection(db, user_id)
        conn.consecutive_failures = 5
        conn.next_retry_at = datetime.utcnow() + timedelta(hours=4)
        conn.last_error = "GarminConnectConnectionError: HTTP 403"
        db.commit()

        reset_connection_backoff(conn)
        db.commit()

        assert conn.consecutive_failures == 0
        assert conn.next_retry_at is None
        assert conn.last_error is None
    finally:
        db.close()


# ---------------------------------------------------------------------------
# _check_and_sync — scheduler skip behavior
# ---------------------------------------------------------------------------

def test_check_and_sync_skips_connection_in_backoff_window(db_setup, monkeypatch) -> None:
    """A connection with next_retry_at in the future must not be synced."""
    from db import session as db_session
    from db import sync_scheduler
    from db.models import UserConnection, UserConfig

    user_id, _ = db_setup
    db = db_session.SessionLocal()
    try:
        conn = _make_connection(db, user_id)
        # Park the connection 2h into the future — well inside the backoff.
        conn.status = "error"
        conn.next_retry_at = datetime.utcnow() + timedelta(hours=2)
        conn.consecutive_failures = 2
        # Stale last_sync so the freshness check would otherwise trigger.
        conn.last_sync = datetime.utcnow() - timedelta(days=1)
        db.add(UserConfig(user_id=user_id))
        db.commit()
    finally:
        db.close()

    sync_calls: list[str] = []

    def _fake_sync_connection(uid, platform, db):
        sync_calls.append(f"{uid}:{platform}")

    monkeypatch.setattr(sync_scheduler, "_sync_connection", _fake_sync_connection)

    sync_scheduler._check_and_sync()

    assert sync_calls == [], (
        f"Backed-off connection must be skipped; was synced as {sync_calls!r}"
    )


def test_check_and_sync_skips_auth_required_connections(db_setup, monkeypatch) -> None:
    """auth_required is terminal — only user reconnect can clear it."""
    from db import session as db_session
    from db import sync_scheduler
    from db.models import UserConfig

    user_id, _ = db_setup
    db = db_session.SessionLocal()
    try:
        conn = _make_connection(db, user_id)
        conn.status = "auth_required"
        # next_retry_at None — proves the skip is on status, not timestamp.
        conn.next_retry_at = None
        conn.last_sync = datetime.utcnow() - timedelta(days=1)
        db.add(UserConfig(user_id=user_id))
        db.commit()
    finally:
        db.close()

    sync_calls: list[str] = []
    monkeypatch.setattr(
        sync_scheduler, "_sync_connection",
        lambda uid, platform, db: sync_calls.append(f"{uid}:{platform}"),
    )

    sync_scheduler._check_and_sync()

    assert sync_calls == [], (
        f"auth_required connection must be skipped; was synced as {sync_calls!r}"
    )


def test_check_and_sync_runs_once_window_has_passed(db_setup, monkeypatch) -> None:
    """When next_retry_at is in the past, the scheduler tries again."""
    from db import session as db_session
    from db import sync_scheduler
    from db.models import UserConfig

    user_id, _ = db_setup
    db = db_session.SessionLocal()
    try:
        conn = _make_connection(db, user_id)
        conn.status = "error"
        conn.next_retry_at = datetime.utcnow() - timedelta(minutes=5)
        conn.consecutive_failures = 2
        conn.last_sync = datetime.utcnow() - timedelta(days=1)
        db.add(UserConfig(user_id=user_id))
        db.commit()
    finally:
        db.close()

    sync_calls: list[str] = []
    monkeypatch.setattr(
        sync_scheduler, "_sync_connection",
        lambda uid, platform, db: sync_calls.append(f"{uid}:{platform}"),
    )

    sync_scheduler._check_and_sync()

    assert sync_calls == [f"{user_id}:garmin"], (
        f"Connection past its retry window must be synced; got {sync_calls!r}"
    )
