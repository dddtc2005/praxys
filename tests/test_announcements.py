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


def test_admin_list_includes_inactive_and_requires_admin(db_with_admin):
    from api.routes.announcements import (
        AnnouncementCreate,
        AnnouncementUpdate,
        create_announcement,
        list_admin_announcements,
        update_announcement,
    )
    from fastapi import HTTPException

    db, admin_id, user_id = db_with_admin
    announcement = create_announcement(
        AnnouncementCreate(title="Maintenance", body="Scheduled."),
        user_id=admin_id,
        db=db,
    )
    update_announcement(
        announcement["id"],
        AnnouncementUpdate(is_active=False),
        user_id=admin_id,
        db=db,
    )

    rows = list_admin_announcements(user_id=admin_id, db=db)
    assert len(rows) == 1
    assert rows[0]["is_active"] is False

    with pytest.raises(HTTPException) as exc:
        list_admin_announcements(user_id=user_id, db=db)
    assert exc.value.status_code == 403



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


def test_translations_round_trip(db_with_admin):
    from api.routes.announcements import create_announcement, get_announcements, AnnouncementCreate
    db, admin_id, user_id = db_with_admin

    payload = AnnouncementCreate(
        title="Higher-resolution zone analysis",
        body="We improved zone accuracy.",
        type="info",
        link_text="Learn more",
        link_url="/science",
        translations={"zh": {
            "title": "更高分辨率的区间分析",
            "body": "我们提升了区间准确度。",
            "link_text": "了解更多",
        }},
    )
    ann = create_announcement(payload, user_id=admin_id, db=db)
    assert ann["translations"]["zh"]["title"] == "更高分辨率的区间分析"
    assert ann["translations"]["zh"]["body"] == "我们提升了区间准确度。"
    assert ann["translations"]["zh"]["link_text"] == "了解更多"
    # Top-level English base is preserved as the fallback.
    assert ann["title"] == "Higher-resolution zone analysis"

    visible = get_announcements(user_id=user_id, db=db)
    assert visible[0]["translations"]["zh"]["title"] == "更高分辨率的区间分析"


def test_serialize_defaults_translations_to_empty(db_with_admin):
    from api.routes.announcements import create_announcement, AnnouncementCreate
    db, admin_id, _ = db_with_admin

    ann = create_announcement(AnnouncementCreate(title="X", body=""), user_id=admin_id, db=db)
    # No translations supplied -> serialized as {} (never null), so the
    # frontend can index translations[locale] safely.
    assert ann["translations"] == {}


def test_update_translations(db_with_admin):
    from api.routes.announcements import create_announcement, update_announcement
    from api.routes.announcements import AnnouncementCreate, AnnouncementUpdate
    db, admin_id, _ = db_with_admin

    ann = create_announcement(AnnouncementCreate(title="X", body="Y"), user_id=admin_id, db=db)
    updated = update_announcement(
        ann["id"],
        AnnouncementUpdate(translations={"zh": {"title": "标题", "body": "正文"}}),
        user_id=admin_id, db=db,
    )
    assert updated["translations"]["zh"]["title"] == "标题"
    assert updated["translations"]["zh"]["body"] == "正文"


def test_blank_translation_fields_stripped(db_with_admin):
    from api.routes.announcements import create_announcement, AnnouncementCreate
    db, admin_id, _ = db_with_admin

    ann = create_announcement(
        AnnouncementCreate(
            title="X", body="Y",
            translations={"zh": {"title": "   ", "body": ""}},
        ),
        user_id=admin_id, db=db,
    )
    # Whitespace-only / empty overrides are dropped so no phantom zh block
    # shadows the English fallback.
    assert ann["translations"] == {}


def test_invalid_translation_locale_rejected(db_with_admin):
    from api.routes.announcements import create_announcement, AnnouncementCreate
    from fastapi import HTTPException
    db, admin_id, _ = db_with_admin

    with pytest.raises(HTTPException) as exc:
        create_announcement(
            AnnouncementCreate(title="X", body="", translations={"fr": {"title": "Bonjour"}}),
            user_id=admin_id, db=db,
        )
    assert exc.value.status_code == 422


def test_invalid_translation_field_rejected(db_with_admin):
    from api.routes.announcements import create_announcement, AnnouncementCreate
    from fastapi import HTTPException
    db, admin_id, _ = db_with_admin

    with pytest.raises(HTTPException) as exc:
        create_announcement(
            AnnouncementCreate(title="X", body="", translations={"zh": {"headline": "x"}}),
            user_id=admin_id, db=db,
        )
    assert exc.value.status_code == 422


def test_invalid_translation_value_rejected(db_with_admin):
    from api.routes.announcements import create_announcement, AnnouncementCreate
    from fastapi import HTTPException
    db, admin_id, _ = db_with_admin

    with pytest.raises(HTTPException) as exc:
        create_announcement(
            AnnouncementCreate(title="X", body="", translations={"zh": {"title": 123}}),  # type: ignore
            user_id=admin_id, db=db,
        )
    assert exc.value.status_code == 422
