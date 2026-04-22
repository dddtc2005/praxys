import json
from unittest.mock import patch

import pytest

from analysis.config import PLATFORM_CAPABILITIES
from tests.test_settings_api import api_client


@pytest.fixture(autouse=True)
def reset_vault():
    from db import crypto

    crypto._vault = None
    try:
        yield
    finally:
        crypto._vault = None


def _store_connection(user_id: str, creds: dict) -> None:
    from db import session as db_session
    from db.crypto import get_vault
    from db.models import UserConnection

    db = db_session.SessionLocal()
    try:
        prefs = {
            key: value
            for key, value in PLATFORM_CAPABILITIES["strava"].items()
            if value
        }
        encrypted_credentials, wrapped_dek = get_vault().encrypt(json.dumps(creds))
        db.add(
            UserConnection(
                user_id=user_id,
                platform="strava",
                encrypted_credentials=encrypted_credentials,
                wrapped_dek=wrapped_dek,
                status="connected",
                preferences=prefs,
            )
        )
        db.commit()
    finally:
        db.close()


def test_trigger_sync_strava_writes_activity_split_and_rotated_tokens(
    api_client,
    monkeypatch,
):
    client, user_id = api_client
    monkeypatch.setenv("PRAXYS_STRAVA_CLIENT_ID", "55555")
    monkeypatch.setenv("PRAXYS_STRAVA_CLIENT_SECRET", "secret-value")

    _store_connection(
        user_id,
        {
            "access_token": "old-token",
            "refresh_token": "refresh-1",
            "expires_at": 1,
        },
    )

    refreshed_creds = {
        "access_token": "new-token",
        "refresh_token": "refresh-2",
        "expires_at": 1776000000,
        "athlete": {"id": 42, "username": "runner-42"},
    }
    activity_rows = [
        {
            "activity_id": "101",
            "date": "2026-04-01",
            "start_time": "2026-04-01T05:00:00Z",
            "activity_type": "running",
            "distance_km": "10.0",
            "duration_sec": "3000.0",
            "avg_power": "245.4",
            "avg_hr": "150.2",
            "avg_pace_sec_km": "300.0",
            "source": "strava",
        }
    ]
    raw_activities = [{"id": 101}]
    lap_rows = [
        {
            "activity_id": "101",
            "split_num": "1",
            "distance_km": "1.0",
            "duration_sec": "285.0",
            "avg_power": "302.4",
            "avg_hr": "151.2",
            "avg_pace_sec_km": "285.0",
        }
    ]

    with (
        patch(
            "sync.strava_sync.refresh_access_token_if_needed",
            return_value=(refreshed_creds, True),
        ) as mock_refresh,
        patch(
            "sync.strava_sync.fetch_activities_api",
            return_value=(activity_rows, raw_activities),
        ) as mock_fetch_activities,
        patch(
            "sync.strava_sync.fetch_activity_laps",
            return_value=lap_rows,
        ) as mock_fetch_laps,
        patch("time.sleep", return_value=None),
    ):
        res = client.post("/api/sync/strava", json={"from_date": "2026-04-01"})

    assert res.status_code == 200, res.text
    assert res.json() == {"status": "started", "source": "strava"}
    mock_refresh.assert_called_once()
    mock_fetch_activities.assert_called_once_with("new-token", "2026-04-01")
    mock_fetch_laps.assert_called_once_with("101", "new-token")

    from db import session as db_session
    from db.crypto import get_vault
    from db.models import Activity, ActivitySplit, UserConnection

    db = db_session.SessionLocal()
    try:
        activity = (
            db.query(Activity)
            .filter(Activity.user_id == user_id, Activity.activity_id == "101")
            .one()
        )
        assert activity.source == "strava"
        assert activity.avg_pace_sec_km == 300.0
        assert activity.avg_pace_min_km == "5:00"

        split = (
            db.query(ActivitySplit)
            .filter(
                ActivitySplit.user_id == user_id,
                ActivitySplit.activity_id == "101",
                ActivitySplit.split_num == 1,
            )
            .one()
        )
        assert split.avg_pace_sec_km == 285.0
        assert split.avg_pace_min_km == "4:45"

        conn = (
            db.query(UserConnection)
            .filter(
                UserConnection.user_id == user_id,
                UserConnection.platform == "strava",
            )
            .one()
        )
        stored_creds = json.loads(
            get_vault().decrypt(conn.encrypted_credentials, conn.wrapped_dek)
        )
        assert stored_creds == refreshed_creds
        assert conn.last_sync is not None
        assert conn.status == "connected"
    finally:
        db.close()

    status_res = client.get("/api/sync/status")
    assert status_res.status_code == 200, status_res.text
    status = status_res.json()["strava"]
    assert status["status"] == "done"
    assert status["connected"] is True
    assert status["error"] is None
    assert status["last_sync"] is not None


def test_run_sync_strava_persists_rotated_tokens_even_when_fetch_fails(
    api_client,
    monkeypatch,
):
    _client, user_id = api_client
    monkeypatch.setenv("PRAXYS_STRAVA_CLIENT_ID", "55555")
    monkeypatch.setenv("PRAXYS_STRAVA_CLIENT_SECRET", "secret-value")

    _store_connection(
        user_id,
        {
            "access_token": "old-token",
            "refresh_token": "refresh-1",
            "expires_at": 1,
        },
    )

    refreshed_creds = {
        "access_token": "new-token",
        "refresh_token": "refresh-2",
        "expires_at": 1776000000,
    }

    from api.routes.sync import _run_sync
    from db import session as db_session
    from db.crypto import get_vault
    from db.models import UserConnection

    with (
        patch(
            "sync.strava_sync.refresh_access_token_if_needed",
            return_value=(refreshed_creds, True),
        ),
        patch(
            "sync.strava_sync.fetch_activities_api",
            side_effect=RuntimeError("activity fetch failed"),
        ),
    ):
        _run_sync(
            user_id,
            "strava",
            {
                "access_token": "old-token",
                "refresh_token": "refresh-1",
                "expires_at": 1,
            },
            "2026-04-01",
        )

    db = db_session.SessionLocal()
    try:
        conn = (
            db.query(UserConnection)
            .filter(
                UserConnection.user_id == user_id,
                UserConnection.platform == "strava",
            )
            .one()
        )
        stored_creds = json.loads(
            get_vault().decrypt(conn.encrypted_credentials, conn.wrapped_dek)
        )
        assert stored_creds == refreshed_creds
        assert conn.status == "error"
    finally:
        db.close()
