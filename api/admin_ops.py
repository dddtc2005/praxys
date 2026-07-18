"""Privacy-safe aggregate data for the admin operations overview.

Phase 1 deliberately combines only Praxys database aggregates and live component
probes. Azure Monitor remains the telemetry source of truth, but its curated
summaries stay explicitly unavailable here until the frontend/backend telemetry
trust boundary from issue #417 is separated.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from api import app_config
from api.routes.status import component_health_snapshot
from api.views import utc_isoformat
from db.models import Feedback, ServiceIncident

logger = logging.getLogger(__name__)

OpsWindow = Literal["24h", "7d", "28d"]
OpsFreshness = Literal["fresh", "stale", "unavailable"]
OpsSource = Literal["praxys_database", "live_probe", "azure_monitor"]
OpsReason = Literal["section_refresh_failed", "azure_telemetry_not_connected"]
OpsSectionWindow = Literal["live", "rolling_1d_7d_30d", "24h", "7d", "28d"]
ComponentStatus = Literal[
    "operational",
    "degraded_performance",
    "partial_outage",
    "major_outage",
]
OverallStatus = Literal["operational", "degraded", "partial_outage", "major_outage"]


class OpsSectionMeta(BaseModel):
    """Source and freshness metadata shared by every overview section."""

    source: OpsSource
    window: OpsSectionWindow
    freshness: OpsFreshness
    as_of: str | None
    reason: OpsReason | None = None


class OpsIncidentCounts(BaseModel):
    total: int
    minor: int
    major: int
    critical: int


class OpsFeedbackCounts(BaseModel):
    needs_review: int
    failed: int
    new: int
    actionable: int
    critical: int
    high: int
    total: int


class OpsActiveIncident(BaseModel):
    id: int
    title: str
    status: Literal["investigating", "identified", "monitoring", "resolved"]
    impact: Literal["minor", "major", "critical"]
    started_at: str | None
    updated_at: str | None


class OpsAttentionData(BaseModel):
    incident_counts: OpsIncidentCounts
    active_incidents: list[OpsActiveIncident]
    feedback: OpsFeedbackCounts


class OpsAttentionSection(OpsSectionMeta):
    data: OpsAttentionData | None = None


class OpsStatusComponent(BaseModel):
    key: str
    name: str
    status: ComponentStatus


class OpsServiceHealthData(BaseModel):
    overall: OverallStatus
    components: list[OpsStatusComponent]


class OpsServiceHealthSection(OpsSectionMeta):
    data: OpsServiceHealthData | None = None


class OpsProductValueData(BaseModel):
    registered_users: int
    dau: int
    wau: int
    mau: int
    directional: bool


class OpsProductValueSection(OpsSectionMeta):
    data: OpsProductValueData | None = None


class OpsUnavailableSection(OpsSectionMeta):
    data: None = None


class OpsLinks(BaseModel):
    users: str
    feedback: str
    incidents: str
    communications: str
    public_status: str
    monitoring_docs: str
    telemetry_trust_issue: str


class OpsSummaryResponse(BaseModel):
    """Typed aggregate contract returned by ``GET /api/admin/ops/summary``."""

    generated_at: str
    window: OpsWindow
    attention: OpsAttentionSection
    service_health: OpsServiceHealthSection
    product_value: OpsProductValueSection
    azure_alerts: OpsUnavailableSection
    platform_health: OpsUnavailableSection
    links: OpsLinks


_SECTION_FAILURE_REASON: OpsReason = "section_refresh_failed"
_AZURE_UNAVAILABLE_REASON: OpsReason = "azure_telemetry_not_connected"


def _fresh_meta(source: OpsSource, window: OpsSectionWindow, as_of: str) -> dict:
    return {
        "source": source,
        "window": window,
        "freshness": "fresh",
        "as_of": as_of,
        "reason": None,
    }


def _unavailable_meta(source: OpsSource, window: OpsSectionWindow, reason: OpsReason) -> dict:
    return {
        "source": source,
        "window": window,
        "freshness": "unavailable",
        "as_of": None,
        "reason": reason,
    }


def _attention_data(db: Session) -> OpsAttentionData:
    incidents = (
        db.query(ServiceIncident)
        .filter(ServiceIncident.status != "resolved")
        .order_by(ServiceIncident.started_at.desc())
        .all()
    )
    incident_counts = {"minor": 0, "major": 0, "critical": 0}
    for incident in incidents:
        if incident.impact in incident_counts:
            incident_counts[incident.impact] += 1

    feedback_rows = (
        db.query(Feedback.status, Feedback.priority, func.count(Feedback.id))
        .group_by(Feedback.status, Feedback.priority)
        .all()
    )
    status_counts: dict[str, int] = {}
    priority_counts = {"critical": 0, "high": 0}
    total = 0
    for status, priority, count in feedback_rows:
        n = int(count)
        total += n
        status_counts[status] = status_counts.get(status, 0) + n
        if status in {"needs_review", "failed"} and priority in priority_counts:
            priority_counts[priority] += n

    needs_review = status_counts.get("needs_review", 0)
    failed = status_counts.get("failed", 0)
    return OpsAttentionData(
        incident_counts=OpsIncidentCounts(
            total=len(incidents),
            minor=incident_counts["minor"],
            major=incident_counts["major"],
            critical=incident_counts["critical"],
        ),
        active_incidents=[
            OpsActiveIncident(
                id=incident.id,
                title=incident.title,
                status=incident.status,
                impact=incident.impact,
                started_at=utc_isoformat(incident.started_at),
                updated_at=utc_isoformat(incident.updated_at),
            )
            for incident in incidents
        ],
        feedback=OpsFeedbackCounts(
            needs_review=needs_review,
            failed=failed,
            new=status_counts.get("new", 0),
            actionable=needs_review + failed,
            critical=priority_counts["critical"],
            high=priority_counts["high"],
            total=total,
        ),
    )


def _service_health_data(db: Session) -> OpsServiceHealthData:
    snapshot = component_health_snapshot(db)
    return OpsServiceHealthData.model_validate(snapshot)


def _product_value_data(db: Session) -> OpsProductValueData:
    registration = app_config.registration_status(db)
    activity = app_config.activity_counts(db)
    return OpsProductValueData(
        registered_users=registration["registered_users"],
        dau=activity["dau"],
        wau=activity["wau"],
        mau=activity["mau"],
        # last_seen_at is an authenticated-request proxy, not trusted client
        # telemetry. Keep the interpretation explicit in the UI.
        directional=True,
    )


def build_ops_summary(db: Session, window: OpsWindow) -> OpsSummaryResponse:
    """Build an aggregate-only operations snapshot with section isolation.

    Each database-backed section degrades independently. A failed query is
    logged, the transaction is rolled back so later sections can continue, and
    only that section becomes unavailable.
    """
    generated_at = utc_isoformat(datetime.utcnow()) or ""

    try:
        attention = OpsAttentionSection(
            **_fresh_meta("praxys_database", "live", generated_at),
            data=_attention_data(db),
        )
    except Exception:
        logger.exception("admin ops: attention section failed")
        db.rollback()
        attention = OpsAttentionSection(
            **_unavailable_meta("praxys_database", "live", _SECTION_FAILURE_REASON)
        )

    try:
        service_health = OpsServiceHealthSection(
            **_fresh_meta("live_probe", "live", generated_at),
            data=_service_health_data(db),
        )
    except Exception:
        logger.exception("admin ops: service health section failed")
        db.rollback()
        service_health = OpsServiceHealthSection(
            **_unavailable_meta("live_probe", "live", _SECTION_FAILURE_REASON)
        )

    try:
        product_value = OpsProductValueSection(
            **_fresh_meta("praxys_database", "rolling_1d_7d_30d", generated_at),
            data=_product_value_data(db),
        )
    except Exception:
        logger.exception("admin ops: product value section failed")
        db.rollback()
        product_value = OpsProductValueSection(
            **_unavailable_meta(
                "praxys_database", "rolling_1d_7d_30d", _SECTION_FAILURE_REASON
            )
        )

    azure_alerts = OpsUnavailableSection(
        **_unavailable_meta("azure_monitor", window, _AZURE_UNAVAILABLE_REASON)
    )
    platform_health = OpsUnavailableSection(
        **_unavailable_meta("azure_monitor", window, _AZURE_UNAVAILABLE_REASON)
    )

    return OpsSummaryResponse(
        generated_at=generated_at,
        window=window,
        attention=attention,
        service_health=service_health,
        product_value=product_value,
        azure_alerts=azure_alerts,
        platform_health=platform_health,
        links=OpsLinks(
            users="/admin/users",
            feedback="/admin/feedback",
            incidents="/admin/incidents",
            communications="/admin/communications",
            public_status="/status",
            monitoring_docs=(
                "https://github.com/praxys-run/praxys/blob/main/docs/ops/"
                "monitoring-and-alerts.md"
            ),
            telemetry_trust_issue="https://github.com/praxys-run/praxys/issues/417",
        ),
    )
