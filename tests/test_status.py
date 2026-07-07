"""Tests for the service status page endpoints (public status + admin incidents)."""
import tempfile

import pytest


@pytest.fixture
def db_with_admin(monkeypatch):
    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    monkeypatch.setenv("DATA_DIR", tmpdir.name)
    monkeypatch.setenv("PRAXYS_LOCAL_ENCRYPTION_KEY", "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=")
    # Scheduler is not started in the test process; mark it intentionally
    # disabled so the Background Sync probe reads operational (the disabled
    # branch) rather than "expected-but-dead" degraded.
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "false")
    from db import session as db_session
    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()
    from db.models import User
    db = db_session.SessionLocal()
    admin_id = "admin-status-test"
    user_id = "user-status-test"
    db.add(User(id=admin_id, email="admin@status.test", hashed_password="x", is_superuser=True))
    db.add(User(id=user_id, email="user@status.test", hashed_password="x", is_superuser=False))
    db.commit()
    try:
        yield db, admin_id, user_id
    finally:
        db.close()
        if db_session.engine is not None:
            db_session.engine.dispose()
        db_session.engine = None
        db_session.SessionLocal = None
        db_session.async_engine = None
        db_session.AsyncSessionLocal = None
        tmpdir.cleanup()


def test_status_all_operational_no_incidents(db_with_admin):
    from api.routes.status import get_status
    db, _, _ = db_with_admin

    status = get_status(db=db)
    assert status["overall"] == "operational"
    keys = {c["key"] for c in status["components"]}
    assert keys == {"api", "database", "sync"}
    assert all(c["status"] == "operational" for c in status["components"])
    assert status["incidents"] == []
    assert status["updated_at"] is not None


def test_create_incident_surfaces_and_drives_overall(db_with_admin):
    from api.routes.status import create_incident, get_status, IncidentCreate
    db, admin_id, _ = db_with_admin

    inc = create_incident(
        IncidentCreate(title="Elevated API latency", impact="major", body="Looking into it."),
        user_id=admin_id, db=db,
    )
    assert inc["id"] is not None
    assert inc["status"] == "investigating"
    assert inc["resolved_at"] is None
    assert len(inc["updates"]) == 1
    assert inc["updates"][0]["body"] == "Looking into it."

    status = get_status(db=db)
    # major impact -> partial_outage banner
    assert status["overall"] == "partial_outage"
    assert len(status["incidents"]) == 1
    assert status["incidents"][0]["title"] == "Elevated API latency"


def test_critical_incident_yields_major_outage(db_with_admin):
    from api.routes.status import create_incident, get_status, IncidentCreate
    db, admin_id, _ = db_with_admin

    create_incident(IncidentCreate(title="Total outage", impact="critical"), user_id=admin_id, db=db)
    assert get_status(db=db)["overall"] == "major_outage"


def test_resolve_moves_incident_to_history(db_with_admin):
    from api.routes.status import (
        create_incident, add_incident_update, get_status,
        get_incident_history, IncidentCreate, IncidentUpdateCreate,
    )
    db, admin_id, _ = db_with_admin

    inc = create_incident(IncidentCreate(title="DB blip", impact="minor"), user_id=admin_id, db=db)
    resolved = add_incident_update(
        inc["id"], IncidentUpdateCreate(status="resolved", body="Fixed."),
        user_id=admin_id, db=db,
    )
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"] is not None
    # Two timeline entries now (open + resolve), newest first.
    assert len(resolved["updates"]) == 2
    assert resolved["updates"][0]["body"] == "Fixed."

    status = get_status(db=db)
    assert status["overall"] == "operational"
    assert status["incidents"] == []

    history = get_incident_history(limit=20, db=db)
    assert len(history) == 1
    assert history[0]["status"] == "resolved"


def test_add_update_transitions_status(db_with_admin):
    from api.routes.status import create_incident, add_incident_update, IncidentCreate, IncidentUpdateCreate
    db, admin_id, _ = db_with_admin

    inc = create_incident(IncidentCreate(title="Sync errors", impact="minor"), user_id=admin_id, db=db)
    updated = add_incident_update(
        inc["id"], IncidentUpdateCreate(status="identified", body="Found the cause."),
        user_id=admin_id, db=db,
    )
    assert updated["status"] == "identified"
    assert updated["resolved_at"] is None


def test_patch_incident_edits_title_and_impact(db_with_admin):
    from api.routes.status import create_incident, update_incident, IncidentCreate, IncidentPatch
    db, admin_id, _ = db_with_admin

    inc = create_incident(IncidentCreate(title="typo ttile", impact="minor"), user_id=admin_id, db=db)
    patched = update_incident(inc["id"], IncidentPatch(title="Fixed title", impact="major"), user_id=admin_id, db=db)
    assert patched["title"] == "Fixed title"
    assert patched["impact"] == "major"


def test_delete_incident(db_with_admin):
    from api.routes.status import create_incident, delete_incident, get_incident_history, IncidentCreate
    db, admin_id, _ = db_with_admin

    inc = create_incident(IncidentCreate(title="Gone soon", impact="minor"), user_id=admin_id, db=db)
    delete_incident(inc["id"], user_id=admin_id, db=db)
    assert get_incident_history(limit=20, db=db) == []


def test_non_admin_cannot_manage_incidents(db_with_admin):
    from api.routes.status import (
        create_incident, add_incident_update, update_incident, delete_incident, list_incidents,
        IncidentCreate, IncidentUpdateCreate, IncidentPatch,
    )
    from fastapi import HTTPException
    db, admin_id, user_id = db_with_admin

    # Seed one incident as admin so the update/delete paths have a target.
    inc = create_incident(IncidentCreate(title="Seed", impact="minor"), user_id=admin_id, db=db)

    for call in (
        lambda: create_incident(IncidentCreate(title="X", impact="minor"), user_id=user_id, db=db),
        lambda: add_incident_update(inc["id"], IncidentUpdateCreate(body="x"), user_id=user_id, db=db),
        lambda: update_incident(inc["id"], IncidentPatch(title="x"), user_id=user_id, db=db),
        lambda: delete_incident(inc["id"], user_id=user_id, db=db),
        lambda: list_incidents(user_id=user_id, db=db),
    ):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 403


def test_invalid_status_and_impact_rejected(db_with_admin):
    from api.routes.status import create_incident, IncidentCreate
    from fastapi import HTTPException
    db, admin_id, _ = db_with_admin

    with pytest.raises(HTTPException) as e1:
        create_incident(IncidentCreate(title="X", status="broken"), user_id=admin_id, db=db)
    assert e1.value.status_code == 422

    with pytest.raises(HTTPException) as e2:
        create_incident(IncidentCreate(title="X", impact="catastrophic"), user_id=admin_id, db=db)
    assert e2.value.status_code == 422


def test_probe_sync_branches(monkeypatch):
    import db.sync_scheduler as sched
    from api.routes.status import _probe_sync

    # Intentionally disabled -> operational (not an outage).
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "false")
    assert _probe_sync() == "operational"

    # Enabled + thread alive -> operational.
    monkeypatch.setenv("PRAXYS_SYNC_SCHEDULER", "true")
    monkeypatch.setattr(sched, "scheduler_running", lambda: True)
    assert _probe_sync() == "operational"

    # Enabled but expected-and-dead -> degraded.
    monkeypatch.setattr(sched, "scheduler_running", lambda: False)
    assert _probe_sync() == "degraded_performance"


def test_probe_database_operational(db_with_admin):
    from api.routes.status import _probe_database
    db, _, _ = db_with_admin
    assert _probe_database(db) == "operational"
