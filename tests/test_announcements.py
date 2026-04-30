"""Tests for system announcement endpoints."""
import tempfile
import pytest


@pytest.fixture
def db_with_admin(monkeypatch):
    tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    monkeypatch.setenv("DATA_DIR", tmpdir.name)
    monkeypatch.setenv("PRAXYS_LOCAL_ENCRYPTION_KEY", "JKkx_5SVHKQDr0HSMrwl0KQHcA0pl5pxsYSLEAQDB4o=")
    from db import session as db_session
    db_session.engine = None
    db_session.SessionLocal = None
    db_session.async_engine = None
    db_session.AsyncSessionLocal = None
    db_session.init_db()
    from db.models import User
    db = db_session.SessionLocal()
    admin_id = "admin-ann-test"
    user_id = "user-ann-test"
    db.add(User(id=admin_id, email="admin@ann.test", hashed_password="x", is_superuser=True))
    db.add(User(id=user_id, email="user@ann.test", hashed_password="x", is_superuser=False))
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


def test_create_and_list_announcement(db_with_admin):
    from api.routes.announcements import create_announcement, get_announcements, AnnouncementCreate
    db, admin_id, user_id = db_with_admin

    payload = AnnouncementCreate(
        title="Test banner",
        body="Please backfill your data.",
        type="info",
        link_text="Settings",
        link_url="/settings",
    )
    ann = create_announcement(payload, user_id=admin_id, db=db)
    assert ann["id"] is not None
    assert ann["title"] == "Test banner"
    assert ann["is_active"] is True

    # Regular user can see active announcements
    visible = get_announcements(user_id=user_id, db=db)
    assert len(visible) == 1
    assert visible[0]["title"] == "Test banner"


def test_non_admin_cannot_create(db_with_admin):
    from api.routes.announcements import create_announcement, AnnouncementCreate
    from fastapi import HTTPException
    db, admin_id, user_id = db_with_admin

    with pytest.raises(HTTPException) as exc:
        create_announcement(AnnouncementCreate(title="X", body=""), user_id=user_id, db=db)
    assert exc.value.status_code == 403


def test_deactivate_hides_from_users(db_with_admin):
    from api.routes.announcements import create_announcement, update_announcement, get_announcements
    from api.routes.announcements import AnnouncementCreate, AnnouncementUpdate
    db, admin_id, user_id = db_with_admin

    ann = create_announcement(AnnouncementCreate(title="X", body=""), user_id=admin_id, db=db)
    update_announcement(ann["id"], AnnouncementUpdate(is_active=False), user_id=admin_id, db=db)

    visible = get_announcements(user_id=user_id, db=db)
    assert len(visible) == 0


def test_delete_announcement(db_with_admin):
    from api.routes.announcements import create_announcement, delete_announcement, get_announcements
    from api.routes.announcements import AnnouncementCreate
    db, admin_id, user_id = db_with_admin

    ann = create_announcement(AnnouncementCreate(title="Gone", body=""), user_id=admin_id, db=db)
    delete_announcement(ann["id"], user_id=admin_id, db=db)

    visible = get_announcements(user_id=user_id, db=db)
    assert len(visible) == 0


def test_invalid_type_rejected(db_with_admin):
    from api.routes.announcements import create_announcement, AnnouncementCreate
    from fastapi import HTTPException
    db, admin_id, _ = db_with_admin

    with pytest.raises(HTTPException) as exc:
        create_announcement(
            AnnouncementCreate(title="X", body="", type="critical"),  # type: ignore
            user_id=admin_id, db=db,
        )
    assert exc.value.status_code == 422
