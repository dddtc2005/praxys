"""System announcement endpoints — site-wide notification banners.

GET /api/announcements        — all authenticated users; returns active banners
POST /api/admin/announcements — admin only; create
PATCH /api/admin/announcements/{id} — admin only; update
DELETE /api/admin/announcements/{id} — admin only; delete
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_current_user_id
from api.views import utc_isoformat, require_admin
from db.session import get_db

router = APIRouter()


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

class AnnouncementCreate(BaseModel):
    """Payload for creating a system announcement."""
    title: str
    body: str
    type: str = "info"
    is_active: bool = True
    link_text: str | None = None
    link_url: str | None = None


class AnnouncementUpdate(BaseModel):
    """Partial update payload — all fields optional."""
    title: str | None = None
    body: str | None = None
    type: str | None = None
    is_active: bool | None = None
    link_text: str | None = None
    link_url: str | None = None


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
