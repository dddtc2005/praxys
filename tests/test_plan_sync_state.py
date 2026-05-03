"""GET /api/plan window-framing + sync_state derivation.

Covers the contract change in the Plan reshape:

- The canonical plan is the AI-authored one (`source='ai'`); Stryd plan
  rows in the same window become `sync_state` flags on AI rows that share
  a date and `stryd_only_dates` for orphan Stryd rows.
- ``?start=&end=`` clamps the response window and is salted into the
  ETag so two clients on different windows can't bleed cache.
- ``cp_current`` was retired — its presence here would mean a partial
  revert of the reshape.
"""
import os
import tempfile
from datetime import date, timedelta

import pytest


@pytest.fixture
def api_client(monkeypatch):
    from fastapi.testclient import TestClient

    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    monkeypatch.setenv("DATA_DIR", tmpdir.name)
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "false")
    monkeypatch.setenv(
        "PRAXYS_LOCAL_ENCRYPTION_KEY",
        "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=",
    )
    monkeypatch.setenv("PRAXYS_JWT_SECRET", "test-secret-plan-sync-state")

    from db import session as db_session
    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    from api.routes import plan as plan_mod
    scratch_root = os.path.join(tmpdir.name, "ai", "stryd_push_status")
    monkeypatch.setattr(plan_mod, "_DATA_DIR", tmpdir.name)
    monkeypatch.setattr(plan_mod, "_STRYD_PUSH_STATUS_DIR", scratch_root)

    from api.main import app
    from api.auth import (
        get_current_user_id, get_data_user_id, require_write_access,
    )
    from db.session import get_db

    user_id = "test-user-plan-sync-state"

    def _override_user():
        return user_id

    def _override_db():
        db = db_session.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_current_user_id] = _override_user
    app.dependency_overrides[get_data_user_id] = _override_user
    app.dependency_overrides[require_write_access] = _override_user
    app.dependency_overrides[get_db] = _override_db

    client = TestClient(app)
    try:
        yield client, user_id
    finally:
        app.dependency_overrides.clear()
        if db_session.engine is not None:
            db_session.engine.dispose()
        if db_session.async_engine is not None:
            import asyncio
            try:
                asyncio.run(db_session.async_engine.dispose())
            except RuntimeError:
                pass
        db_session.engine = None
        db_session.SessionLocal = None
        db_session.async_engine = None
        db_session.AsyncSessionLocal = None
        tmpdir.cleanup()


def _seed_rows(user_id: str, rows: list[dict]) -> None:
    """Insert TrainingPlan rows. Each dict needs date/source/workout_type."""
    from db import session as db_session
    from db.models import TrainingPlan

    db = db_session.SessionLocal()
    try:
        for r in rows:
            db.add(TrainingPlan(
                user_id=user_id,
                date=r["date"],
                source=r["source"],
                workout_type=r.get("workout_type", ""),
                workout_description=r.get("workout_description", ""),
                external_id=r.get("external_id"),
                planned_duration_min=r.get("planned_duration_min"),
            ))
        db.commit()
    finally:
        db.close()


def test_get_plan_returns_window_with_source_tag(api_client):
    """Both AI and Stryd plan rows in the window come back, each tagged
    with its ``source`` so the UI can label them. Past and far-future
    rows are clipped by the default [today, +14d] window.
    """
    client, user_id = api_client
    today = date.today()
    ai_day = today + timedelta(days=2)
    stryd_day = today + timedelta(days=4)
    out_of_window = today + timedelta(days=30)

    _seed_rows(user_id, [
        {"date": ai_day, "source": "ai", "workout_type": "easy"},
        {"date": stryd_day, "source": "stryd", "workout_type": "tempo"},
        # Past AI row — out of the default forward window.
        {"date": today - timedelta(days=2), "source": "ai", "workout_type": "rest"},
        # Future AI row beyond the default 14-day window.
        {"date": out_of_window, "source": "ai", "workout_type": "long_run"},
    ])

    res = client.get("/api/plan")
    assert res.status_code == 200, res.text
    body = res.json()
    workouts = body["workouts"]
    # Both in-window rows surface, sorted by date and tagged by source.
    assert [(w["date"], w["source"]) for w in workouts] == [
        (ai_day.isoformat(), "ai"),
        (stryd_day.isoformat(), "stryd"),
    ]
    # The retired ``cp_current`` field must not return.
    assert "cp_current" not in body
    # Window echo helps clients page without restating the math themselves.
    assert body["window"] == {
        "start": today.isoformat(),
        "end": (today + timedelta(days=14)).isoformat(),
    }


def test_ai_row_takes_precedence_when_date_collides(api_client):
    """When both AI and Stryd schedule the same date, the AI row wins
    as the visible workout and the Stryd row contributes only to
    ``sync_state`` derivation."""
    client, user_id = api_client
    target = date.today() + timedelta(days=2)
    _seed_rows(user_id, [
        {"date": target, "source": "ai", "workout_type": "threshold"},
        {"date": target, "source": "stryd", "workout_type": "tempo_stryd"},
    ])
    workouts = client.get("/api/plan").json()["workouts"]
    assert len(workouts) == 1
    assert workouts[0]["source"] == "ai"
    assert workouts[0]["workout_type"] == "threshold"


def test_sync_state_synced_when_external_id_matches_push_log(api_client):
    """An AI row + Stryd row at the same date with matching ids → ``synced``."""
    from api.routes.plan import _save_push_status

    client, user_id = api_client
    target = date.today() + timedelta(days=3)
    _save_push_status(user_id, {
        target.isoformat(): {"workout_id": "stryd-abc", "status": "pushed"},
    })
    _seed_rows(user_id, [
        {"date": target, "source": "ai", "workout_type": "threshold"},
        {
            "date": target, "source": "stryd",
            "workout_type": "threshold", "external_id": "stryd-abc",
        },
    ])

    body = client.get("/api/plan").json()
    assert body["workouts"][0]["sync_state"] == "synced"


def test_sync_state_mismatch_when_external_id_diverges(api_client):
    """Stryd row exists but its id doesn't match the push log → ``mismatch``.

    This is the case the UI must catch before re-pushing — typically the
    user edited the workout directly inside Stryd's calendar.
    """
    from api.routes.plan import _save_push_status

    client, user_id = api_client
    target = date.today() + timedelta(days=4)
    _save_push_status(user_id, {
        target.isoformat(): {"workout_id": "stryd-old", "status": "pushed"},
    })
    _seed_rows(user_id, [
        {"date": target, "source": "ai", "workout_type": "intervals"},
        {
            "date": target, "source": "stryd",
            "workout_type": "intervals", "external_id": "stryd-edited",
        },
    ])

    body = client.get("/api/plan").json()
    assert body["workouts"][0]["sync_state"] == "mismatch"


def test_sync_state_synced_when_pushed_but_stryd_not_yet_resynced(api_client):
    """The brief window after a successful push but before the next
    Stryd sync pulls the row back in: push log has the workout_id but
    no Stryd row exists yet. Must read as ``synced`` for consumers
    that don't share the frontend's optimistic ``pushStatus`` map
    (mini-program, MCP). Otherwise they'd offer to push again.
    """
    from api.routes.plan import _save_push_status

    client, user_id = api_client
    target = date.today() + timedelta(days=6)
    _save_push_status(user_id, {
        target.isoformat(): {"workout_id": "stryd-just-pushed", "status": "pushed"},
    })
    _seed_rows(user_id, [
        {"date": target, "source": "ai", "workout_type": "easy"},
    ])
    body = client.get("/api/plan").json()
    assert body["workouts"][0]["sync_state"] == "synced"


def test_sync_state_uses_workout_type_match_when_multiple_stryd_rows(api_client):
    """Stryd allows multiple workouts on the same date (AM run + PM
    strides, race + shakeout). The AI sync_state derivation must
    pick the row whose ``workout_type`` matches the AI row, not
    arbitrarily the last-iterated one.
    """
    from api.routes.plan import _save_push_status

    client, user_id = api_client
    target = date.today() + timedelta(days=2)
    _save_push_status(user_id, {
        target.isoformat(): {"workout_id": "stryd-threshold", "status": "pushed"},
    })
    _seed_rows(user_id, [
        # AI plan: a threshold workout.
        {"date": target, "source": "ai", "workout_type": "threshold"},
        # Stryd has *both* the matched threshold (with our pushed id)
        # AND an unrelated easy run added by the user. Without the
        # workout_type-match, the easy row could collapse the threshold
        # row in stryd_by_date and the AI row would mis-read mismatch.
        {
            "date": target, "source": "stryd",
            "workout_type": "easy", "external_id": "stryd-other-easy",
        },
        {
            "date": target, "source": "stryd",
            "workout_type": "threshold", "external_id": "stryd-threshold",
        },
    ])
    body = client.get("/api/plan").json()
    ai_row = next(w for w in body["workouts"] if w["source"] == "ai")
    assert ai_row["sync_state"] == "synced"


def test_sync_state_not_synced_when_no_stryd_row(api_client):
    client, user_id = api_client
    target = date.today() + timedelta(days=5)
    _seed_rows(user_id, [
        {"date": target, "source": "ai", "workout_type": "easy"},
    ])
    body = client.get("/api/plan").json()
    assert body["workouts"][0]["sync_state"] == "not_synced"


def test_stryd_only_row_surfaces_with_source_tag(api_client):
    """A Stryd row with no AI counterpart still appears in ``workouts``
    so the user sees their imported / coach-authored workouts. It carries
    ``source='stryd'`` and no ``sync_state`` (it lives natively on Stryd
    so the AI-vs-Stryd sync question doesn't apply).
    """
    client, user_id = api_client
    ai_day = date.today() + timedelta(days=2)
    orphan_day = date.today() + timedelta(days=4)
    _seed_rows(user_id, [
        {"date": ai_day, "source": "ai", "workout_type": "easy"},
        {"date": orphan_day, "source": "stryd", "workout_type": "race"},
    ])
    workouts = client.get("/api/plan").json()["workouts"]
    by_date = {w["date"]: w for w in workouts}
    assert by_date[ai_day.isoformat()]["source"] == "ai"
    stryd_row = by_date[orphan_day.isoformat()]
    assert stryd_row["source"] == "stryd"
    assert "sync_state" not in stryd_row


def test_window_query_params_clamp_response(api_client):
    client, user_id = api_client
    today = date.today()
    near = today + timedelta(days=2)
    far = today + timedelta(days=20)
    _seed_rows(user_id, [
        {"date": near, "source": "ai", "workout_type": "easy"},
        {"date": far, "source": "ai", "workout_type": "long_run"},
    ])

    res = client.get(
        f"/api/plan?start={today.isoformat()}&end={(today + timedelta(days=7)).isoformat()}"
    )
    assert res.status_code == 200
    near_only = res.json()
    assert [w["date"] for w in near_only["workouts"]] == [near.isoformat()]

    res = client.get(
        f"/api/plan?start={today.isoformat()}&end={far.isoformat()}"
    )
    assert res.status_code == 200
    both = res.json()
    assert [w["date"] for w in both["workouts"]] == [
        near.isoformat(), far.isoformat(),
    ]


def test_window_etag_does_not_collide_across_windows(api_client):
    """Different windows must hash to different ETags — otherwise a 304
    revalidation would replay the wrong window's body."""
    client, _ = api_client
    today = date.today()
    a = client.get(f"/api/plan?start={today.isoformat()}&end={(today + timedelta(days=7)).isoformat()}")
    b = client.get(f"/api/plan?start={today.isoformat()}&end={(today + timedelta(days=21)).isoformat()}")
    assert a.headers["etag"] != b.headers["etag"]


def test_invalid_window_returns_400(api_client):
    client, _ = api_client
    today = date.today()
    inverted = client.get(
        f"/api/plan?start={today.isoformat()}&end={(today - timedelta(days=1)).isoformat()}"
    )
    assert inverted.status_code == 400

    bad_format = client.get("/api/plan?start=not-a-date")
    assert bad_format.status_code == 400


def test_oversized_window_returns_400(api_client):
    """Cap is 365 days. ``?end=2099-12-31`` against today shouldn't
    force the server to ship a multi-year payload — the cap should
    reject it with a clear 400 instead of silently clamping."""
    client, _ = api_client
    today = date.today()
    huge = client.get(
        f"/api/plan?start={today.isoformat()}&end={(today + timedelta(days=400)).isoformat()}"
    )
    assert huge.status_code == 400, huge.text
    assert "365" in huge.text


def test_sync_target_reflects_stryd_connection(api_client, monkeypatch):
    """``sync_target`` is ``"stryd"`` only when the user is actually
    connected to Stryd — the Plan UI hides the sync column otherwise."""
    client, _ = api_client

    # No connections → sync_target null.
    body = client.get("/api/plan").json()
    assert body["sync_target"] is None

    # Inject a stryd connection at the config layer.
    from analysis import config as cfg_mod

    real_loader = cfg_mod.load_config_from_db

    def _with_stryd(user_id, db):
        cfg = real_loader(user_id, db)
        cfg.connections = list({*cfg.connections, "stryd"})
        return cfg

    monkeypatch.setattr("api.packs.load_config_from_db", _with_stryd)
    body = client.get(
        "/api/plan", headers={"If-None-Match": '"never"'},
    ).json()
    assert body["sync_target"] == "stryd"
