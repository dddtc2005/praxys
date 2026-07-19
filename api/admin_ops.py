"""Privacy-safe aggregate data for the admin operations overview."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Literal, TypeVar

from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from api import app_config
from api.admin_azure_monitor import (
    AzureSectionSnapshot,
    azure_portal_links,
    get_ops_telemetry,
)
from api.routes.status import component_health_snapshot
from api.views import utc_isoformat
from db.models import Feedback, ServiceIncident

logger = logging.getLogger(__name__)

OpsWindow = Literal["24h", "7d", "28d"]
OpsFreshness = Literal["fresh", "stale", "unavailable"]
OpsSource = Literal["praxys_database", "live_probe", "azure_monitor"]
OpsReason = Literal[
    "section_refresh_failed",
    "azure_telemetry_not_configured",
    "azure_sdk_unavailable",
    "azure_query_failed",
    "azure_query_partial",
    "azure_query_timed_out",
]
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
    postgres_active_connections: int | None = None
    postgres_max_connections: int | None = None
    postgres_connection_utilization: float | None = None


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


class OpsServiceTelemetryData(BaseModel):
    requests: int
    failed_requests: int
    server_errors: int
    failed_request_rate: float | None
    server_error_rate: float | None
    p95_request_ms: float | None
    availability_checks: int
    failed_availability_checks: int
    availability_rate: float | None
    p95_availability_ms: float | None
    database_health_failures: int


class OpsServiceTelemetrySection(OpsSectionMeta):
    data: OpsServiceTelemetryData | None = None


class OpsAlertSeverityCounts(BaseModel):
    sev0: int
    sev1: int
    sev2: int
    sev3: int
    sev4: int


class OpsAlertStateCounts(BaseModel):
    new: int
    acknowledged: int
    closed: int


class OpsAlertRuleSummary(BaseModel):
    rule: str
    severity: str
    firing: int
    resolved: int
    last_changed_at: str | None


class OpsAzureAlertsData(BaseModel):
    total: int
    firing: int
    resolved: int
    severity: OpsAlertSeverityCounts
    states: OpsAlertStateCounts
    rules: list[OpsAlertRuleSummary]


class OpsAzureAlertsSection(OpsSectionMeta):
    data: OpsAzureAlertsData | None = None


class OpsProductSurfaceTelemetry(BaseModel):
    surface: str
    app_users: int
    today_users: int
    today_reach_rate: float | None
    decision_prompts: int
    decision_responses: int
    decision_response_rate: float | None
    reported_value_rate: float | None
    repeated_users: int
    repeated_rate: float | None


class OpsCoachTelemetry(BaseModel):
    insight_type: str
    useful_votes: int
    total_votes: int
    useful_rate: float | None


class OpsProductTelemetryData(BaseModel):
    surfaces: list[OpsProductSurfaceTelemetry]
    coach: list[OpsCoachTelemetry]


class OpsProductTelemetrySection(OpsSectionMeta):
    data: OpsProductTelemetryData | None = None


class OpsSyncTelemetry(BaseModel):
    platform: str
    attempts: int
    successes: int
    failures: int
    failure_rate: float | None


class OpsSystemicFailureTelemetry(BaseModel):
    platform: str
    failure_class: str
    failures: int
    affected_users: int


class OpsConnectionTelemetry(BaseModel):
    platform: str
    flow: str
    stage: str
    outcome: str
    attempts: int


class OpsPlatformHealthData(BaseModel):
    sync: list[OpsSyncTelemetry]
    systemic_affected_users: int
    systemic_failures: list[OpsSystemicFailureTelemetry]
    connections: list[OpsConnectionTelemetry]


class OpsPlatformHealthSection(OpsSectionMeta):
    data: OpsPlatformHealthData | None = None


class OpsLinks(BaseModel):
    users: str
    feedback: str
    incidents: str
    communications: str
    public_status: str
    monitoring_docs: str
    azure_alerts: str
    azure_logs: str
    # Retained until old frontend bundles have aged out after backend-first deploys.
    telemetry_trust_issue: str


class OpsSummaryResponse(BaseModel):
    """Typed aggregate contract returned by ``GET /api/admin/ops/summary``."""

    generated_at: str
    window: OpsWindow
    attention: OpsAttentionSection
    service_health: OpsServiceHealthSection
    product_value: OpsProductValueSection
    service_telemetry: OpsServiceTelemetrySection
    product_telemetry: OpsProductTelemetrySection
    azure_alerts: OpsAzureAlertsSection
    platform_health: OpsPlatformHealthSection
    links: OpsLinks


_SECTION_FAILURE_REASON: OpsReason = "section_refresh_failed"
_AzureData = TypeVar("_AzureData", bound=BaseModel)
_AzureSection = TypeVar("_AzureSection", bound=OpsSectionMeta)


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


def _azure_meta(snapshot: AzureSectionSnapshot, window: OpsWindow) -> dict[str, Any]:
    return {
        "source": "azure_monitor",
        "window": window,
        "freshness": snapshot.freshness,
        "as_of": utc_isoformat(snapshot.as_of),
        "reason": snapshot.reason,
    }


def _azure_section(
    snapshot: AzureSectionSnapshot,
    window: OpsWindow,
    data_model: type[_AzureData],
    section_model: type[_AzureSection],
) -> _AzureSection:
    data = data_model.model_validate(snapshot.data) if snapshot.data is not None else None
    return section_model(**_azure_meta(snapshot, window), data=data)


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
    active_connections: int | None = None
    max_connections: int | None = None
    utilization: float | None = None
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        try:
            row = db.execute(
                text(
                    "SELECT count(*) AS active_connections, "
                    "current_setting('max_connections')::int AS max_connections "
                    "FROM pg_stat_activity"
                )
            ).mappings().one()
            active_connections = int(row["active_connections"])
            max_connections = int(row["max_connections"])
            utilization = (
                active_connections / max_connections if max_connections > 0 else None
            )
        except SQLAlchemyError:
            logger.warning(
                "admin ops: PostgreSQL connection snapshot failed",
                exc_info=True,
            )
            db.rollback()
    snapshot.update(
        {
            "postgres_active_connections": active_connections,
            "postgres_max_connections": max_connections,
            "postgres_connection_utilization": utilization,
        }
    )
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

    # The Azure sections can wait up to the overall telemetry deadline. End the
    # read transaction first so degraded Azure Monitor cannot pin a pooled
    # PostgreSQL connection for every concurrent admin request.
    db.rollback()
    azure = get_ops_telemetry(window)
    service_telemetry = _azure_section(
        azure["service"],
        window,
        OpsServiceTelemetryData,
        OpsServiceTelemetrySection,
    )
    product_telemetry = _azure_section(
        azure["product"],
        "28d",
        OpsProductTelemetryData,
        OpsProductTelemetrySection,
    )
    azure_alerts = _azure_section(
        azure["alerts"],
        window,
        OpsAzureAlertsData,
        OpsAzureAlertsSection,
    )
    platform_health = _azure_section(
        azure["platform"],
        window,
        OpsPlatformHealthData,
        OpsPlatformHealthSection,
    )
    azure_alerts_url, azure_logs_url = azure_portal_links()

    return OpsSummaryResponse(
        generated_at=generated_at,
        window=window,
        attention=attention,
        service_health=service_health,
        product_value=product_value,
        service_telemetry=service_telemetry,
        product_telemetry=product_telemetry,
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
            azure_alerts=azure_alerts_url,
            azure_logs=azure_logs_url,
            telemetry_trust_issue="https://github.com/praxys-run/praxys/issues/417",
        ),
    )
