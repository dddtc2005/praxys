"""Integration tests for the AI plan endpoints in api/routes/ai.py.

Covers:
- POST /api/plan/upload — replace (default) and merge modes
- PUT /api/plan/{date} — upsert single workout
- DELETE /api/plan/{date} — delete single day

These guard the contract change in #128 (delete-and-recreate replaced by
explicit modes + per-day operations) so a future refactor can't quietly
revert to "wipe everything on every push" semantics.
"""
import tempfile
from datetime import date, timedelta

import pytest


@pytest.fixture
def api_client(monkeypatch):
    """FastAPI TestClient with an isolated SQLite DB and a stable test user."""
    from fastapi.testclient import TestClient

    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    monkeypatch.setenv("DATA_DIR", tmpdir.name)
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "false")
    monkeypatch.setenv(
        "PRAXYS_LOCAL_ENCRYPTION_KEY", "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o="
    )

    from db import session as db_session
    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()

    from api.main import app
    from api.auth import require_write_access, get_data_user_id
    from db.session import get_db

    test_user_id = "test-user-plan-endpoints"

    def _override_user():
        return test_user_id

    def _override_db():
        db = db_session.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[require_write_access] = _override_user
    app.dependency_overrides[get_data_user_id] = _override_user
    app.dependency_overrides[get_db] = _override_db

    client = TestClient(app)
    try:
        yield client, test_user_id
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


def _seed_plan(user_id: str, days: list[tuple[str, str, str]]):
    """Insert (date_iso, workout_type, description) rows as source='ai'."""
    from datetime import datetime
    from db import session as db_session
    from db.models import TrainingPlan

    db = db_session.SessionLocal()
    try:
        for date_iso, wt, desc in days:
            db.add(TrainingPlan(
                user_id=user_id,
                date=datetime.strptime(date_iso, "%Y-%m-%d").date(),
                workout_type=wt,
                workout_description=desc,
                source="ai",
            ))
        db.commit()
    finally:
        db.close()


def _list_plan_rows(user_id: str) -> list[dict]:
    from db import session as db_session
    from db.models import TrainingPlan

    db = db_session.SessionLocal()
    try:
        rows = db.query(TrainingPlan).filter(
            TrainingPlan.user_id == user_id,
            TrainingPlan.source == "ai",
        ).order_by(TrainingPlan.date).all()
        return [
            {
                "date": r.date.isoformat(),
                "workout_type": r.workout_type,
                "workout_description": r.workout_description,
            }
            for r in rows
        ]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# POST /api/plan/upload — replace mode (default, backwards-compat)
# ---------------------------------------------------------------------------


class TestUploadReplaceMode:
    def test_replace_is_default(self, api_client):
        client, user_id = api_client
        future = (date.today() + timedelta(days=2)).isoformat()
        far = (date.today() + timedelta(days=20)).isoformat()
        _seed_plan(user_id, [
            (future, "easy", "stale entry, must be deleted"),
            (far, "rest", "also stale"),
        ])

        new_date = (date.today() + timedelta(days=5)).isoformat()
        res = client.post("/api/plan/upload", json={
            "csv": "date,workout_type,workout_description\n"
                   f"{new_date},long_run,Fresh row\n",
        })
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "saved"
        assert body["rows"] == 1
        assert body["mode"] == "replace"

        rows = _list_plan_rows(user_id)
        assert len(rows) == 1, "replace mode wiped existing future rows"
        assert rows[0]["date"] == new_date

    def test_replace_preserves_past_rows(self, api_client):
        client, user_id = api_client
        past = (date.today() - timedelta(days=3)).isoformat()
        future = (date.today() + timedelta(days=3)).isoformat()
        _seed_plan(user_id, [
            (past, "easy", "history"),
            (future, "easy", "to be replaced"),
        ])

        new_date = (date.today() + timedelta(days=5)).isoformat()
        res = client.post("/api/plan/upload?mode=replace", json={
            "csv": f"date,workout_type\n{new_date},rest\n",
        })
        assert res.status_code == 200, res.text

        rows = _list_plan_rows(user_id)
        dates = [r["date"] for r in rows]
        assert past in dates, "past rows must survive a replace"
        assert future not in dates
        assert new_date in dates


# ---------------------------------------------------------------------------
# POST /api/plan/upload — merge mode (the new behavior)
# ---------------------------------------------------------------------------


class TestUploadMergeMode:
    def test_merge_only_touches_payload_dates(self, api_client):
        client, user_id = api_client
        d1 = (date.today() + timedelta(days=1)).isoformat()
        d2 = (date.today() + timedelta(days=2)).isoformat()
        d3 = (date.today() + timedelta(days=3)).isoformat()
        _seed_plan(user_id, [
            (d1, "easy", "keep me"),
            (d2, "easy", "stale, will be replaced"),
            (d3, "rest", "keep me too"),
        ])

        res = client.post("/api/plan/upload?mode=merge", json={
            "csv": "date,workout_type,workout_description\n"
                   f"{d2},threshold,Updated\n",
        })
        assert res.status_code == 200, res.text
        assert res.json()["mode"] == "merge"

        rows = {r["date"]: r for r in _list_plan_rows(user_id)}
        assert rows[d1]["workout_description"] == "keep me"
        assert rows[d2]["workout_type"] == "threshold"
        assert rows[d2]["workout_description"] == "Updated"
        assert rows[d3]["workout_description"] == "keep me too"

    def test_merge_inserts_new_dates(self, api_client):
        client, user_id = api_client
        d_existing = (date.today() + timedelta(days=1)).isoformat()
        _seed_plan(user_id, [(d_existing, "easy", "existing")])

        d_new = (date.today() + timedelta(days=10)).isoformat()
        res = client.post("/api/plan/upload?mode=merge", json={
            "csv": f"date,workout_type\n{d_new},long_run\n",
        })
        assert res.status_code == 200, res.text

        rows = _list_plan_rows(user_id)
        assert len(rows) == 2
        assert {r["date"] for r in rows} == {d_existing, d_new}


# ---------------------------------------------------------------------------
# PUT /api/plan/{date}
# ---------------------------------------------------------------------------


class TestUpsertPlanDay:
    def test_put_inserts_new_day(self, api_client):
        client, user_id = api_client
        target = (date.today() + timedelta(days=4)).isoformat()
        res = client.put(f"/api/plan/{target}", json={
            "workout_type": "easy",
            "planned_duration_min": 45,
            "target_power_min": 150,
            "target_power_max": 200,
            "workout_description": "Easy aerobic run",
        })
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["date"] == target
        assert body["workout_type"] == "easy"
        assert body["planned_duration_min"] == 45
        assert body["source"] == "ai"

    def test_put_replaces_existing_day_only(self, api_client):
        client, user_id = api_client
        target = (date.today() + timedelta(days=4)).isoformat()
        other = (date.today() + timedelta(days=5)).isoformat()
        _seed_plan(user_id, [
            (target, "easy", "old"),
            (other, "rest", "untouched"),
        ])

        res = client.put(f"/api/plan/{target}", json={
            "workout_type": "threshold",
            "workout_description": "New workout",
        })
        assert res.status_code == 200, res.text

        rows = {r["date"]: r for r in _list_plan_rows(user_id)}
        assert rows[target]["workout_type"] == "threshold"
        assert rows[target]["workout_description"] == "New workout"
        assert rows[other]["workout_description"] == "untouched"

    def test_put_rejects_bad_date(self, api_client):
        client, _ = api_client
        res = client.put("/api/plan/not-a-date", json={"workout_type": "easy"})
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /api/plan/{date}
# ---------------------------------------------------------------------------


class TestDeletePlanDay:
    def test_delete_removes_only_target_day(self, api_client):
        client, user_id = api_client
        target = (date.today() + timedelta(days=4)).isoformat()
        other = (date.today() + timedelta(days=5)).isoformat()
        _seed_plan(user_id, [
            (target, "easy", "to be deleted"),
            (other, "rest", "must survive"),
        ])

        res = client.delete(f"/api/plan/{target}")
        assert res.status_code == 200, res.text
        assert res.json()["rows"] == 1

        rows = _list_plan_rows(user_id)
        dates = [r["date"] for r in rows]
        assert target not in dates
        assert other in dates

    def test_delete_missing_day_is_noop(self, api_client):
        client, _ = api_client
        target = (date.today() + timedelta(days=99)).isoformat()
        res = client.delete(f"/api/plan/{target}")
        assert res.status_code == 200, res.text
        assert res.json()["rows"] == 0

    def test_delete_rejects_bad_date(self, api_client):
        client, _ = api_client
        res = client.delete("/api/plan/2026-99-99")
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# Mode validation guard
# ---------------------------------------------------------------------------


def test_upload_rejects_invalid_mode(api_client):
    client, _ = api_client
    res = client.post("/api/plan/upload?mode=bogus", json={
        "csv": "date,workout_type\n2026-12-31,easy\n",
    })
    # FastAPI returns 422 for query validation failures
    assert res.status_code == 422
