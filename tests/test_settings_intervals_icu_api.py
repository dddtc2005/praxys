"""Settings API for intervals.icu connection."""
from unittest.mock import patch

import pytest

from tests.test_settings_api import api_client as _api_client_fixture  # noqa: F401


@pytest.fixture(autouse=True)
def reset_vault():
    from db import crypto

    crypto._vault = None
    try:
        yield
    finally:
        crypto._vault = None


@pytest.fixture
def api_client(monkeypatch, _api_client_fixture):  # noqa: F811
    """Unpack the (client, user_id) tuple from the shared fixture."""
    return _api_client_fixture


@pytest.fixture
def user_id(api_client):
    _, uid = api_client
    return uid


@pytest.fixture
def db(user_id):
    """Yield an open DB session (same engine as the test client) and seed UserConfig."""
    from db import session as db_session
    from db.models import UserConfig

    session = db_session.SessionLocal()
    try:
        # Ensure a UserConfig row exists for the test user so auto-populate tests work.
        if not session.query(UserConfig).filter_by(user_id=user_id).first():
            session.add(UserConfig(user_id=user_id, preferences={}))
            session.commit()
        yield session
    finally:
        session.close()


def test_post_connects_intervals_icu_on_valid_credentials(api_client, user_id):
    """Validate credentials against fetch_athlete_profile_api, then persist."""
    client, _ = api_client
    with patch("sync.intervals_icu_sync.fetch_athlete_profile_api") as mock:
        mock.return_value = {"id": "i123456", "sportSettings": []}
        resp = client.post(
            "/api/settings/connections/intervals_icu",
            json={"athlete_id": "i123456", "api_key": "pat"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "connected"


def test_post_rejects_invalid_intervals_icu_credentials(api_client, user_id):
    """Handler returns 200 with status=error (consistent with all other platforms)."""
    client, _ = api_client
    from sync.intervals_icu_sync import IntervalsIcuUnauthorized

    with patch(
        "sync.intervals_icu_sync.fetch_athlete_profile_api",
        side_effect=IntervalsIcuUnauthorized("401"),
    ):
        resp = client.post(
            "/api/settings/connections/intervals_icu",
            json={"athlete_id": "i123456", "api_key": "bad"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "error"
    assert "invalid" in body["message"].lower() or "credentials" in body["message"].lower()


def test_post_requires_athlete_id_and_api_key(api_client, user_id):
    """Missing api_key -> 200 with status=error (Pydantic allows None; handler validates)."""
    client, _ = api_client
    resp = client.post(
        "/api/settings/connections/intervals_icu",
        json={"athlete_id": "i123456"},
    )
    # api_key is None -> handler returns {"status": "error", "message": "...required"}
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "error"


def test_post_auto_populates_preferences_when_no_other_source(api_client, user_id, db):
    """First connect with no other platforms -> preferences auto-set to intervals_icu."""
    client, _ = api_client
    from db.models import UserConfig

    with patch("sync.intervals_icu_sync.fetch_athlete_profile_api") as mock:
        mock.return_value = {"id": "i123456", "sportSettings": []}
        resp = client.post(
            "/api/settings/connections/intervals_icu",
            json={"athlete_id": "i123456", "api_key": "pat"},
        )
    assert resp.status_code == 200, resp.text
    db.expire_all()
    cfg = db.query(UserConfig).filter_by(user_id=user_id).one()
    assert cfg.preferences.get("activities") == "intervals_icu"
    assert cfg.preferences.get("recovery") == "intervals_icu"


def test_post_does_not_override_existing_preferences(api_client, user_id, db):
    """If the user already has Garmin preferred, keep that selection."""
    client, _ = api_client
    from db.models import UserConfig

    cfg = db.query(UserConfig).filter_by(user_id=user_id).one()
    cfg.preferences = {"activities": "garmin"}
    db.commit()

    with patch("sync.intervals_icu_sync.fetch_athlete_profile_api") as mock:
        mock.return_value = {"id": "i123456", "sportSettings": []}
        client.post(
            "/api/settings/connections/intervals_icu",
            json={"athlete_id": "i123456", "api_key": "pat"},
        )
    db.expire_all()
    db.refresh(cfg)
    assert cfg.preferences["activities"] == "garmin"
