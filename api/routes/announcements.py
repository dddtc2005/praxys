"""System announcement endpoints — site-wide notification banners.

GET /api/announcements        — all authenticated users; returns active banners
POST /api/admin/announcements — admin only; create
PATCH /api/admin/announcements/{id} — admin only; update
DELETE /api/admin/announcements/{id} — admin only; delete

Issue #355: announcements are bilingual. The top-level ``title`` / ``body`` /
``link_text`` are the canonical base (English) fallback; ``translations`` holds
per-locale overrides (``{"zh": {"title", "body", "link_text"}}``). Mirrors the
AiInsight.translations contract (#103) so a ``zh`` user never sees an
English-only banner against localized UI chrome. Authoring both language
versions before release is what fixes the "mixed Chinese and English" report.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_current_user_id
from api.views import utc_isoformat, require_admin
from db.session import get_db

router = APIRouter()

# Locales that may carry a translation override. Top-level fields are the
# English base, so only non-English locales meaningfully override; ``en`` is
# accepted for symmetry but redundant with the top-level fields.
_ALLOWED_LOCALES = {"en", "zh"}
# Per-locale fields an admin may translate. Everything else on the row
# (``type``, ``is_active``, ``link_url``) is language-neutral.
_TRANSLATABLE_FIELDS = {"title", "body", "link_text"}


def _normalize_translations(raw) -> dict:
    """Validate + clean an incoming ``translations`` payload.

    Returns a dict of ``{locale: {field: str}}`` with blank fields dropped and
    empty locale blocks removed, so ``{"zh": {"title": "  "}}`` normalizes to
    ``{}`` rather than persisting a phantom override. Raises HTTP 422 on any
    unknown locale / field or non-string value.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise HTTPException(422, "translations must be an object keyed by locale")
    cleaned: dict = {}
    for locale, fields in raw.items():
        if locale not in _ALLOWED_LOCALES:
            raise HTTPException(422, f"unsupported translation locale: {locale}")
        if not isinstance(fields, dict):
            raise HTTPException(422, f"translations[{locale}] must be an object")
        block: dict = {}
        for key, value in fields.items():
            if key not in _TRANSLATABLE_FIELDS:
                raise HTTPException(422, f"unsupported translation field: {key}")
            if value is None:
                continue
            if not isinstance(value, str):
                raise HTTPException(422, f"translations[{locale}][{key}] must be a string")
            trimmed = value.strip()
            if trimmed:
                block[key] = trimmed
        if block:
            cleaned[locale] = block
    return cleaned


def _serialize(ann) -> dict:
    """Serialize a SystemAnnouncement ORM row to a response dict."""
    return {
        "id": ann.id,
        "title": ann.title,
        "body": ann.body,
        "type": ann.type,
        "is_active": ann.is_active,
        "link_text": ann.link_text,
        "link_url": ann.link_url,
        "translations": ann.translations or {},
        "created_at": utc_isoformat(ann.created_at),
        "updated_at": utc_isoformat(ann.updated_at),
    }


# ---------------------------------------------------------------------------
# Public — all authenticated users
# ---------------------------------------------------------------------------

@router.get("/announcements")
def get_announcements(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Return all active system announcements."""
    from db.models import SystemAnnouncement
    rows = (
        db.query(SystemAnnouncement)
        .filter(SystemAnnouncement.is_active == True)  # noqa: E712
        .order_by(SystemAnnouncement.created_at.desc())
        .all()
    )
    return [_serialize(r) for r in rows]


# ---------------------------------------------------------------------------
# Admin CRUD
# ---------------------------------------------------------------------------


@router.get("/admin/announcements")
def list_admin_announcements(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Return all announcements, including inactive rows. Admin only."""
    require_admin(user_id, db)
    from db.models import SystemAnnouncement

    rows = db.query(SystemAnnouncement).order_by(SystemAnnouncement.created_at.desc()).all()
    return [_serialize(row) for row in rows]


class AnnouncementCreate(BaseModel):
    """Payload for creating a system announcement."""
    title: str
    body: str
    type: str = "info"
    is_active: bool = True
    link_text: str | None = None
    link_url: str | None = None
    # {"zh": {"title", "body", "link_text"}} — see module docstring.
    translations: dict | None = None


class AnnouncementUpdate(BaseModel):
    """Partial update payload — all fields optional."""
    title: str | None = None
    body: str | None = None
    type: str | None = None
    is_active: bool | None = None
    link_text: str | None = None
    link_url: str | None = None
    translations: dict | None = None


@router.post("/admin/announcements")
def create_announcement(
    payload: AnnouncementCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Create a system announcement. Admin only."""
    require_admin(user_id, db)
    from db.models import SystemAnnouncement
    if payload.type not in ("info", "warning", "success"):
        raise HTTPException(422, "type must be info, warning, or success")
    ann = SystemAnnouncement(
        title=payload.title,
        body=payload.body,
        type=payload.type,
        is_active=payload.is_active,
        link_text=payload.link_text,
        link_url=payload.link_url,
        translations=_normalize_translations(payload.translations),
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return _serialize(ann)


@router.patch("/admin/announcements/{ann_id}")
def update_announcement(
    ann_id: int,
    payload: AnnouncementUpdate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Update a system announcement. Admin only."""
    require_admin(user_id, db)
    from db.models import SystemAnnouncement
    ann = db.query(SystemAnnouncement).filter(SystemAnnouncement.id == ann_id).first()
    if not ann:
        raise HTTPException(404, "Announcement not found")
    if payload.title is not None:
        ann.title = payload.title
    if payload.body is not None:
        ann.body = payload.body
    if payload.type is not None:
        if payload.type not in ("info", "warning", "success"):
            raise HTTPException(422, "type must be info, warning, or success")
        ann.type = payload.type
    if payload.is_active is not None:
        ann.is_active = payload.is_active
    if payload.link_text is not None:
        ann.link_text = payload.link_text
    if payload.link_url is not None:
        ann.link_url = payload.link_url
    if payload.translations is not None:
        # Full replace of the translation blob — the admin form always submits
        # the complete set for the announcement.
        ann.translations = _normalize_translations(payload.translations)
    ann.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(ann)
    return _serialize(ann)


@router.delete("/admin/announcements/{ann_id}")
def delete_announcement(
    ann_id: int,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Delete a system announcement. Admin only."""
    require_admin(user_id, db)
    from db.models import SystemAnnouncement
    ann = db.query(SystemAnnouncement).filter(SystemAnnouncement.id == ann_id).first()
    if not ann:
        raise HTTPException(404, "Announcement not found")
    db.delete(ann)
    db.commit()
    return {"deleted": ann_id}
