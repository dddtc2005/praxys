"""Service status endpoints — public status page + admin incident management.

Public (no auth), so users can check service health even when they cannot log
in — the whole point of a status page:

    GET /api/status            — overall status + component health + active incidents
    GET /api/status/incidents  — recent incident history (active + resolved)

Admin (require_admin):

    GET    /api/admin/incidents                 — all incidents (management view)
    POST   /api/admin/incidents                 — open an incident
    POST   /api/admin/incidents/{id}/updates    — append a timeline update
    PATCH  /api/admin/incidents/{id}            — edit title / impact
    DELETE /api/admin/incidents/{id}            — delete an incident

Modelled on Atlassian Statuspage / GitHub Status: automated component probes
(API, Database, Background Sync) combine with operator-declared incidents to
produce a single overall banner state.
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.auth import get_current_user_id
from api.views import require_admin, utc_isoformat
from db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

# --- Vocabularies (validated at the route layer; stored as stable strings) ---
INCIDENT_STATUSES = ("investigating", "identified", "monitoring", "resolved")
INCIDENT_IMPACTS = ("minor", "major", "critical")

# Component health states, ascending severity. Kept separate from the overall
# banner label so the frontend can colour each component independently.
_COMPONENT_SEVERITY = {
    "operational": 0,
    "degraded_performance": 1,
    "partial_outage": 2,
    "major_outage": 3,
}
# Overall banner label per max severity across components + active incidents.
_SEVERITY_TO_OVERALL = {
    0: "operational",
    1: "degraded",
    2: "partial_outage",
    3: "major_outage",
}
# Active-incident impact -> severity contribution to the overall banner.
_IMPACT_SEVERITY = {"minor": 1, "major": 2, "critical": 3}

# Fallback prose when an operator posts a status transition without a message.
# Incident copy is operator-authored English (like GitHub Status); the status
# page *chrome* is localized, incident bodies are not.
_DEFAULT_UPDATE_BODY = {
    "investigating": "We are investigating this issue.",
    "identified": "The cause has been identified and a fix is being worked on.",
    "monitoring": "A fix has been applied and we are monitoring the results.",
    "resolved": "This incident has been resolved.",
}


def _naive_utc(dt: datetime | None) -> datetime | None:
    """Normalize an (optionally tz-aware) datetime to naive UTC for storage.

    DB timestamps are naive ``datetime.utcnow()`` values; a tz-aware payload
    (e.g. an ISO string with an offset) must be converted so later arithmetic
    (``resolved_at - started_at``) doesn't mix aware and naive datetimes.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _validate_status(status: str) -> None:
    if status not in INCIDENT_STATUSES:
        raise HTTPException(422, f"status must be one of {', '.join(INCIDENT_STATUSES)}")


def _validate_impact(impact: str) -> None:
    if impact not in INCIDENT_IMPACTS:
        raise HTTPException(422, f"impact must be one of {', '.join(INCIDENT_IMPACTS)}")


# ---------------------------------------------------------------------------
# Component health probes
# ---------------------------------------------------------------------------

def _probe_database(db: Session) -> str:
    """Trivial ``SELECT 1`` liveness — same check as /api/health/ready."""
    from sqlalchemy import text
    try:
        db.execute(text("SELECT 1"))
        return "operational"
    except Exception:
        logger.exception("status: database probe failed")
        return "major_outage"


def _probe_sync() -> str:
    """Background sync scheduler health.

    Reports operational when the scheduler thread is alive. If the operator
    intentionally disabled it (``PRAXYS_SYNC_SCHEDULER=false``) we also report
    operational — manual sync still works, so a deliberate config choice must
    not read as a public outage. Only an *expected-but-dead* scheduler degrades.
    """
    from api.env_compat import getenv_compat
    from db.sync_scheduler import scheduler_running
    enabled = (getenv_compat("SYNC_SCHEDULER", "true") or "true").lower() != "false"
    if not enabled:
        return "operational"
    return "operational" if scheduler_running() else "degraded_performance"


def component_health_snapshot(db: Session) -> dict:
    """Return live component health without reading incident records."""
    components = [
        {"key": "api", "name": "API", "status": "operational"},
        {"key": "database", "name": "Database", "status": _probe_database(db)},
        {"key": "sync", "name": "Background Sync", "status": _probe_sync()},
    ]
    severities = [_COMPONENT_SEVERITY.get(c["status"], 0) for c in components]
    return {
        "overall": _SEVERITY_TO_OVERALL.get(max(severities, default=0), "operational"),
        "components": components,
    }


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _serialize_update(u) -> dict:
    return {
        "id": u.id,
        "status": u.status,
        "body": u.body,
        "created_at": utc_isoformat(u.created_at),
    }


def _serialize_incident(inc, include_updates: bool = True) -> dict:
    d = {
        "id": inc.id,
        "title": inc.title,
        "status": inc.status,
        "impact": inc.impact,
        "started_at": utc_isoformat(inc.started_at),
        "resolved_at": utc_isoformat(inc.resolved_at),
        "created_at": utc_isoformat(inc.created_at),
        "updated_at": utc_isoformat(inc.updated_at),
    }
    if include_updates:
        # Newest update first, matching the status-page convention of showing
        # the latest state at the top of an incident.
        ups = sorted(inc.updates, key=lambda u: (u.created_at or datetime.min), reverse=True)
        d["updates"] = [_serialize_update(u) for u in ups]
    return d


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

@router.get("/status")
def get_status(db: Session = Depends(get_db)) -> dict:
    """Public — overall status, component health, and active incidents.

    Never raises on a DB fault: the database probe downgrades the component to
    ``major_outage`` and the incident read is best-effort, so the page still
    renders (and correctly shows red) during an outage.
    """
    from db.models import ServiceIncident

    component_snapshot = component_health_snapshot(db)
    components = component_snapshot["components"]

    active: list = []
    try:
        active = (
            db.query(ServiceIncident)
            .filter(ServiceIncident.status != "resolved")
            .order_by(ServiceIncident.started_at.desc())
            .all()
        )
    except Exception:
        logger.exception("status: failed to load active incidents")

    severities = [_COMPONENT_SEVERITY.get(c["status"], 0) for c in components]
    severities += [_IMPACT_SEVERITY.get(i.impact, 1) for i in active]
    overall = _SEVERITY_TO_OVERALL.get(max(severities, default=0), "operational")

    return {
        "overall": overall,
        "components": components,
        "incidents": [_serialize_incident(i) for i in active],
        "updated_at": utc_isoformat(datetime.utcnow()),
    }


@router.get("/status/incidents")
def get_incident_history(limit: int = 20, db: Session = Depends(get_db)) -> list[dict]:
    """Public — recent incident history (active + resolved), newest first."""
    from db.models import ServiceIncident
    limit = max(1, min(limit, 100))
    rows = (
        db.query(ServiceIncident)
        .order_by(ServiceIncident.started_at.desc())
        .limit(limit)
        .all()
    )
    return [_serialize_incident(r) for r in rows]


# ---------------------------------------------------------------------------
# Admin incident management
# ---------------------------------------------------------------------------

class IncidentCreate(BaseModel):
    """Payload to open an incident (seeds the timeline with one update)."""
    title: str
    impact: str = "minor"           # minor | major | critical
    status: str = "investigating"   # investigating | identified | monitoring | resolved
    body: str = ""                  # opening update message; defaulted when blank
    started_at: datetime | None = None


class IncidentUpdateCreate(BaseModel):
    """Payload to append a timeline update, optionally transitioning status."""
    body: str = ""
    status: str | None = None


class IncidentPatch(BaseModel):
    """Partial edit of an incident's title / impact (corrections)."""
    title: str | None = None
    impact: str | None = None


@router.get("/admin/incidents")
def list_incidents(
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Admin — all incidents (newest first) for the management view."""
    require_admin(user_id, db)
    from db.models import ServiceIncident
    rows = (
        db.query(ServiceIncident)
        .order_by(ServiceIncident.started_at.desc())
        .all()
    )
    return [_serialize_incident(r) for r in rows]


@router.post("/admin/incidents")
def create_incident(
    payload: IncidentCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Admin — open an incident and seed its timeline with the first update."""
    require_admin(user_id, db)
    _validate_status(payload.status)
    _validate_impact(payload.impact)
    if not payload.title.strip():
        raise HTTPException(422, "title is required")
    from db.models import ServiceIncident, ServiceIncidentUpdate

    now = datetime.utcnow()
    inc = ServiceIncident(
        title=payload.title.strip(),
        status=payload.status,
        impact=payload.impact,
        started_at=_naive_utc(payload.started_at) or now,
        resolved_at=now if payload.status == "resolved" else None,
    )
    db.add(inc)
    db.flush()  # assign inc.id before creating the child update
    db.add(ServiceIncidentUpdate(
        incident_id=inc.id,
        status=payload.status,
        body=payload.body.strip() or _DEFAULT_UPDATE_BODY[payload.status],
    ))
    db.commit()
    db.refresh(inc)
    return _serialize_incident(inc)


@router.post("/admin/incidents/{incident_id}/updates")
def add_incident_update(
    incident_id: int,
    payload: IncidentUpdateCreate,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Admin — append a timeline update, optionally transitioning the status.

    Transitioning to ``resolved`` stamps ``resolved_at``; transitioning away
    from ``resolved`` (a re-open) clears it.
    """
    require_admin(user_id, db)
    from db.models import ServiceIncident, ServiceIncidentUpdate
    inc = db.query(ServiceIncident).filter(ServiceIncident.id == incident_id).first()
    if not inc:
        raise HTTPException(404, "Incident not found")

    new_status = payload.status or inc.status
    _validate_status(new_status)
    now = datetime.utcnow()
    if new_status != inc.status:
        inc.status = new_status
        inc.resolved_at = (inc.resolved_at or now) if new_status == "resolved" else None
    inc.updated_at = now
    db.add(ServiceIncidentUpdate(
        incident_id=inc.id,
        status=new_status,
        body=payload.body.strip() or _DEFAULT_UPDATE_BODY[new_status],
    ))
    db.commit()
    db.refresh(inc)
    return _serialize_incident(inc)


@router.patch("/admin/incidents/{incident_id}")
def update_incident(
    incident_id: int,
    payload: IncidentPatch,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Admin — correct an incident's title / impact (status moves via updates)."""
    require_admin(user_id, db)
    from db.models import ServiceIncident
    inc = db.query(ServiceIncident).filter(ServiceIncident.id == incident_id).first()
    if not inc:
        raise HTTPException(404, "Incident not found")
    if payload.title is not None:
        if not payload.title.strip():
            raise HTTPException(422, "title cannot be empty")
        inc.title = payload.title.strip()
    if payload.impact is not None:
        _validate_impact(payload.impact)
        inc.impact = payload.impact
    inc.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(inc)
    return _serialize_incident(inc)


@router.delete("/admin/incidents/{incident_id}")
def delete_incident(
    incident_id: int,
    user_id: str = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> dict:
    """Admin — delete an incident (cascades to its timeline updates)."""
    require_admin(user_id, db)
    from db.models import ServiceIncident
    inc = db.query(ServiceIncident).filter(ServiceIncident.id == incident_id).first()
    if not inc:
        raise HTTPException(404, "Incident not found")
    db.delete(inc)
    db.commit()
    return {"deleted": incident_id}
