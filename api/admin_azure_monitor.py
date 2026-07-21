"""Trusted Azure Monitor aggregates for the admin operations console.

The browser never supplies KQL, resource IDs, or query parameters beyond the
allowlisted time window. Queries run in the context of the backend Application
Insights resource so frontend RUM cannot enter trusted operational summaries.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import logging
import os
import re
import threading
import time
from typing import Any, Callable, Literal
from urllib.parse import urlparse

import httpx
from azure.core.exceptions import AzureError

logger = logging.getLogger(__name__)

AzureWindow = Literal["24h", "7d", "28d"]
AzureFreshness = Literal["fresh", "stale", "unavailable"]
AzureReason = Literal[
    "azure_telemetry_not_configured",
    "azure_sdk_unavailable",
    "azure_query_failed",
    "azure_query_partial",
    "azure_query_timed_out",
]

_RESOURCE_ENV = "PRAXYS_BACKEND_APPINSIGHTS_RESOURCE_ID"
_RESOURCE_RE = re.compile(
    r"^/subscriptions/(?P<subscription>[0-9a-fA-F-]{36})/"
    r"resourceGroups/(?P<resource_group>[A-Za-z0-9._()-]+)/"
    r"providers/Microsoft\.Insights/components/(?P<component>[A-Za-z0-9._-]+)$",
    re.IGNORECASE,
)
_WINDOWS: dict[AzureWindow, timedelta] = {
    "24h": timedelta(days=1),
    "7d": timedelta(days=7),
    "28d": timedelta(days=28),
}
_QUERY_VERSION = "2026-07-19-v1"
_FRESH_TTL_SECONDS = 180.0
_NEGATIVE_TTL_SECONDS = 20.0
_TOTAL_DEADLINE_SECONDS = 12.0
_STALE_LIMIT_SECONDS = {
    "alerts": 15 * 60.0,
    "service": 15 * 60.0,
    "product": 60 * 60.0,
    "platform": 15 * 60.0,
}
_SECTION_NAMES = ("alerts", "service", "product", "platform")
_SYSTEMIC_FAILURE_CLASSES = (
    "rate_limited",
    "captcha_required",
    "access_blocked",
    "token_rejected",
    "mfa_unattended",
    "platform_error",
    "network_error",
    "unknown",
)
_SYSTEMIC_CLUSTER_WINDOW = "15m"
_SYSTEMIC_CLUSTER_MIN_USERS = 5


class AzureMonitorQueryError(RuntimeError):
    """Expected Azure query failure with a stable admin-facing reason."""

    def __init__(self, reason: AzureReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class AzureSectionSnapshot:
    """One cached Azure-backed section returned to ``api.admin_ops``."""

    freshness: AzureFreshness
    as_of: datetime | None
    reason: AzureReason | None
    data: dict[str, Any] | None


@dataclass(frozen=True)
class _CacheEntry:
    data: dict[str, Any]
    as_of: datetime
    cached_at: float


_CACHE: dict[tuple[str, str, str, str], _CacheEntry] = {}
_FAILURES: dict[tuple[str, str, str, str], tuple[float, AzureReason]] = {}
_LOCKS: dict[tuple[str, str, str, str], threading.Lock] = {}
_IN_FLIGHT: dict[
    tuple[str, str, str, str],
    Future[AzureSectionSnapshot],
] = {}
_STATE_LOCK = threading.Lock()
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="admin-azure")


_SERVICE_QUERY = r"""
let rid = tolower("__RESOURCE_ID__");
let request_summary =
    requests
    | where tolower(_ResourceId) == rid
    | where isempty(operation_SyntheticSource)
    | where url !contains "/api/health"
        and url !contains "/api/admin/ops/summary"
    | summarize
        requests=tolong(sum(itemCount)),
        failed_requests=tolong(sumif(itemCount, tobool(success) == false)),
        server_errors=tolong(sumif(itemCount, toint(resultCode) between (500 .. 599))),
        // Resource-context Application Insights exposes duration as real milliseconds.
        p95_request_ms=todouble(percentilew(duration, itemCount, 95));
let availability_summary =
    availabilityResults
    | where tolower(_ResourceId) == rid
    | summarize
        availability_checks=tolong(sum(itemCount)),
        failed_availability_checks=tolong(sumif(itemCount, tobool(success) == false)),
        // Resource-context Application Insights exposes duration as real milliseconds.
        p95_availability_ms=todouble(percentilew(duration, itemCount, 95));
let db_health =
    union isfuzzy=true
        (customEvents
            | where tolower(_ResourceId) == rid and name == "praxys.db_health"
            | project events=todouble(itemCount)),
        (customMetrics
            | where tolower(_ResourceId) == rid and name == "praxys.db_health"
            | project events=coalesce(valueSum, value, todouble(valueCount), 0.0))
    | summarize database_health_failures=tolong(sum(events));
request_summary
| extend join_key=1
| join kind=fullouter (availability_summary | extend join_key=1) on join_key
| join kind=fullouter (db_health | extend join_key=1) on join_key
| project
    requests=coalesce(requests, 0),
    failed_requests=coalesce(failed_requests, 0),
    server_errors=coalesce(server_errors, 0),
    failed_request_rate=iif(
        coalesce(requests, 0) > 0,
        todouble(failed_requests) / todouble(requests),
        real(null)
    ),
    server_error_rate=iif(
        coalesce(requests, 0) > 0,
        todouble(server_errors) / todouble(requests),
        real(null)
    ),
    p95_request_ms,
    availability_checks=coalesce(availability_checks, 0),
    failed_availability_checks=coalesce(failed_availability_checks, 0),
    availability_rate=iif(
        coalesce(availability_checks, 0) > 0,
        1.0 - todouble(failed_availability_checks) / todouble(availability_checks),
        real(null)
    ),
    p95_availability_ms,
    database_health_failures=coalesce(database_health_failures, 0)
"""


_PRODUCT_QUERY = r"""
let rid = tolower("__RESOURCE_ID__");
let product =
    union isfuzzy=true
        (customEvents
            | where tolower(_ResourceId) == rid and name == "praxys.product_event"
            | project
                timestamp,
                event_name=tostring(customDimensions["event_name"]),
                response=tostring(customDimensions["response"]),
                surface=tostring(customDimensions["surface"]),
                user=tostring(customDimensions["user_id_hash"]),
                events=todouble(itemCount)),
        (customMetrics
            | where tolower(_ResourceId) == rid and name == "praxys.product_event"
            | project
                timestamp,
                event_name=tostring(customDimensions["event_name"]),
                response=tostring(customDimensions["response"]),
                surface=tostring(customDimensions["surface"]),
                user=tostring(customDimensions["user_id_hash"]),
                events=coalesce(valueSum, value, todouble(valueCount), 0.0));
let repeated =
    product
    | where event_name == "today_brief_rendered" and isnotempty(user)
    | summarize active_weeks=dcount(startofweek(timestamp)) by user, surface
    | summarize
        repeated_users=tolong(countif(active_weeks >= 2)),
        repeated_base_users=tolong(count())
        by surface;
let surface_dimensions =
    product
    | where isnotempty(surface)
    | distinct surface;
let app_user_summary =
    product
    | where event_name == "app_opened" and isnotempty(user)
    | summarize app_users=tolong(dcount(user)) by surface;
let today_user_summary =
    product
    | where event_name == "today_brief_rendered" and isnotempty(user)
    | summarize today_users=tolong(dcount(user)) by surface;
let response_summary =
    product
    | summarize
        prompts=sumif(events, event_name == "today_feedback_shown"),
        responses=sumif(events, event_name == "today_feedback_submitted"),
        changed_plan=sumif(
            events,
            event_name == "today_feedback_submitted" and response == "changed_plan"
        ),
        confirmed_plan=sumif(
            events,
            event_name == "today_feedback_submitted" and response == "confirmed_plan"
        ),
        not_training=sumif(
            events,
            event_name == "today_feedback_submitted" and response == "not_training"
        )
        by surface;
let surface_summary =
    surface_dimensions
    | join kind=leftouter app_user_summary on surface
    | join kind=leftouter today_user_summary on surface
    | join kind=leftouter response_summary on surface
    | join kind=leftouter repeated on surface
    | extend
        app_users=coalesce(app_users, 0),
        today_users=coalesce(today_users, 0),
        prompts=coalesce(prompts, 0.0),
        responses=coalesce(responses, 0.0),
        changed_plan=coalesce(changed_plan, 0.0),
        confirmed_plan=coalesce(confirmed_plan, 0.0),
        not_training=coalesce(not_training, 0.0),
        repeated_users=coalesce(repeated_users, 0),
        repeated_base_users=coalesce(repeated_base_users, 0),
        eligible_responses=responses - not_training
    | project
        row_kind="surface",
        dimension=surface,
        app_users,
        today_users,
        today_reach_rate=iif(
            app_users > 0,
            todouble(today_users) / todouble(app_users),
            real(null)
        ),
        prompts,
        responses,
        response_rate=iif(prompts > 0, responses / prompts, real(null)),
        reported_value_rate=iif(
            eligible_responses > 0,
            (changed_plan + confirmed_plan) / eligible_responses,
            real(null)
        ),
        repeated_users,
        repeated_rate=iif(
            repeated_base_users > 0,
            todouble(repeated_users) / todouble(repeated_base_users),
            real(null)
        ),
        up=real(null),
        total=real(null),
        useful_rate=real(null);
let coach =
    union isfuzzy=true
        (customEvents
            | where tolower(_ResourceId) == rid and name == "praxys.coach_feedback"
            | project
                insight_type=tostring(customDimensions["insight_type"]),
                vote=tostring(customDimensions["vote"]),
                events=todouble(itemCount)),
        (customMetrics
            | where tolower(_ResourceId) == rid and name == "praxys.coach_feedback"
            | project
                insight_type=tostring(customDimensions["insight_type"]),
                vote=tostring(customDimensions["vote"]),
                events=coalesce(valueSum, value, todouble(valueCount), 0.0))
    | summarize up=sumif(events, vote == "up"), total=sum(events) by insight_type
    | project
        row_kind="coach",
        dimension=insight_type,
        app_users=long(null),
        today_users=long(null),
        today_reach_rate=real(null),
        prompts=real(null),
        responses=real(null),
        response_rate=real(null),
        reported_value_rate=real(null),
        repeated_users=long(null),
        repeated_rate=real(null),
        up,
        total,
        useful_rate=iif(total > 0, up / total, real(null));
union surface_summary, coach
| order by row_kind asc, dimension asc
"""


_PLATFORM_QUERY = rf"""
let rid = tolower("__RESOURCE_ID__");
let signals =
    union isfuzzy=true
        (customEvents
            | where tolower(_ResourceId) == rid
                and name in ("praxys.sync", "praxys.connection")
            | project
                timestamp,
                signal=name,
                platform=tostring(customDimensions["platform"]),
                flow=tostring(customDimensions["flow"]),
                stage=tostring(customDimensions["stage"]),
                outcome=tostring(customDimensions["outcome"]),
                failure_class=tostring(customDimensions["failure_class"]),
                user=tostring(customDimensions["user_id_hash"]),
                events=todouble(itemCount)),
        (customMetrics
            | where tolower(_ResourceId) == rid
                and name in ("praxys.sync", "praxys.connection")
            | project
                timestamp,
                signal=name,
                platform=tostring(customDimensions["platform"]),
                flow=tostring(customDimensions["flow"]),
                stage=tostring(customDimensions["stage"]),
                outcome=tostring(customDimensions["outcome"]),
                failure_class=tostring(customDimensions["failure_class"]),
                user=tostring(customDimensions["user_id_hash"]),
                events=coalesce(valueSum, value, todouble(valueCount), 0.0));
let sync_summary =
    signals
    | where signal == "praxys.sync"
    | summarize
        attempts=sum(events),
        successes=sumif(events, outcome == "success"),
        failures=sumif(events, outcome == "failure")
        by platform
    | project
        row_kind="sync",
        platform,
        flow="",
        stage="",
        outcome="",
        failure_class="",
        attempts,
        successes,
        failures,
        failure_rate=iif(attempts > 0, failures / attempts, real(null)),
        affected_users=long(null);
let systemic_signals =
    signals
    | where signal == "praxys.sync"
        and outcome == "failure"
        and failure_class in ({",".join(f'"{value}"' for value in _SYSTEMIC_FAILURE_CLASSES)})
        and isnotempty(user)
    | extend cluster_start=bin(timestamp, {_SYSTEMIC_CLUSTER_WINDOW});
let systemic_clusters =
    systemic_signals
    | summarize
        cluster_failures=sum(events),
        cluster_users=tolong(dcount(user))
        by cluster_start, platform
    | where cluster_users >= {_SYSTEMIC_CLUSTER_MIN_USERS};
let qualifying_systemic_signals =
    systemic_signals
    | join kind=inner (
        systemic_clusters
        | project cluster_start, platform
    ) on cluster_start, platform;
let systemic_total =
    qualifying_systemic_signals
    | summarize
        failures=sum(events),
        affected_users=tolong(dcount(user))
    | project
        row_kind="failure_total",
        platform="",
        flow="",
        stage="",
        outcome="failure",
        failure_class="",
        attempts=real(null),
        successes=real(null),
        failures,
        failure_rate=real(null),
        affected_users;
let systemic_failures =
    qualifying_systemic_signals
    | summarize
        failures=sum(events),
        affected_users=tolong(dcount(user))
        by platform, failure_class
    | order by affected_users desc, failures desc
    | take 12
    | project
        row_kind="failure",
        platform,
        flow="",
        stage="",
        outcome="failure",
        failure_class,
        attempts=real(null),
        successes=real(null),
        failures,
        failure_rate=real(null),
        affected_users;
let connections =
    signals
    | where signal == "praxys.connection"
    | summarize attempts=sum(events) by platform, flow, stage, outcome
    | order by attempts desc
    | take 24
    | project
        row_kind="connection",
        platform,
        flow,
        stage,
        outcome,
        failure_class="",
        attempts,
        successes=real(null),
        failures=real(null),
        failure_rate=real(null),
        affected_users=long(null);
union sync_summary, systemic_total, systemic_failures, connections
| order by row_kind asc, platform asc, attempts desc
"""


def _configured_resource_id() -> str | None:
    value = os.environ.get(_RESOURCE_ENV, "").strip().rstrip("/")
    if not value:
        return None
    if not _RESOURCE_RE.fullmatch(value):
        raise ValueError(f"{_RESOURCE_ENV} is not a backend Application Insights resource ID")
    return value


def _resource_parts(resource_id: str) -> re.Match[str]:
    match = _RESOURCE_RE.fullmatch(resource_id)
    if match is None:
        raise ValueError("Invalid backend Application Insights resource ID")
    return match


@lru_cache(maxsize=1)
def _credential() -> Any:
    try:
        if os.environ.get("WEBSITE_SITE_NAME"):
            from azure.identity import ManagedIdentityCredential

            client_id = os.environ.get("AZURE_CLIENT_ID")
            return (
                ManagedIdentityCredential(client_id=client_id)
                if client_id
                else ManagedIdentityCredential()
            )

        from azure.identity import DefaultAzureCredential

        return DefaultAzureCredential()
    except ImportError as exc:
        raise AzureMonitorQueryError(
            "azure_sdk_unavailable",
            "azure-identity is unavailable",
        ) from exc


@lru_cache(maxsize=1)
def _logs_client() -> Any:
    try:
        from azure.monitor.query import LogsQueryClient
    except ImportError as exc:
        raise AzureMonitorQueryError(
            "azure_sdk_unavailable",
            "azure-monitor-query is unavailable",
        ) from exc

    return LogsQueryClient(
        _credential(),
        retry_total=1,
        retry_connect=1,
        retry_read=1,
        retry_status=1,
        retry_backoff_factor=0.5,
    )


@lru_cache(maxsize=1)
def _arm_client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(10.0, connect=2.0),
        headers={"User-Agent": "praxys-admin-ops/1"},
    )


def _table_rows(table: Any) -> list[dict[str, Any]]:
    columns = [getattr(column, "name", str(column)) for column in table.columns]
    return [dict(zip(columns, row, strict=True)) for row in table.rows]


def _query_rows(
    resource_id: str,
    window: AzureWindow,
    query: str,
) -> list[dict[str, Any]]:
    try:
        from azure.monitor.query import LogsQueryStatus
    except ImportError as exc:
        raise AzureMonitorQueryError(
            "azure_sdk_unavailable",
            "azure-monitor-query is unavailable",
        ) from exc

    scoped_query = query.replace("__RESOURCE_ID__", resource_id.lower())
    response = _logs_client().query_resource(
        resource_id,
        scoped_query,
        timespan=_WINDOWS[window],
        server_timeout=8,
        connection_timeout=2,
        read_timeout=10,
    )
    if response.status != LogsQueryStatus.SUCCESS:
        raise AzureMonitorQueryError(
            "azure_query_partial",
            "Azure Monitor returned a partial query result",
        )

    rows: list[dict[str, Any]] = []
    for table in response.tables:
        rows.extend(_table_rows(table))
    return rows


def _as_int(value: Any) -> int:
    if value is None:
        return 0
    return int(round(float(value)))


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _bounded_label(value: Any, *, fallback: str = "unknown", limit: int = 120) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = " ".join(value.split())[:limit]
    return normalized or fallback


def _alert_rule_label(value: Any) -> str:
    normalized = _bounded_label(value, limit=240)
    if normalized.startswith("/"):
        return normalized.rstrip("/").rsplit("/", 1)[-1][:160] or "unknown"
    return normalized[:160]


def _query_service(resource_id: str, window: AzureWindow) -> dict[str, Any]:
    rows = _query_rows(resource_id, window, _SERVICE_QUERY)
    row = rows[0] if rows else {}
    return {
        "requests": _as_int(row.get("requests")),
        "failed_requests": _as_int(row.get("failed_requests")),
        "server_errors": _as_int(row.get("server_errors")),
        "failed_request_rate": _as_float(row.get("failed_request_rate")),
        "server_error_rate": _as_float(row.get("server_error_rate")),
        "p95_request_ms": _as_float(row.get("p95_request_ms")),
        "availability_checks": _as_int(row.get("availability_checks")),
        "failed_availability_checks": _as_int(
            row.get("failed_availability_checks")
        ),
        "availability_rate": _as_float(row.get("availability_rate")),
        "p95_availability_ms": _as_float(row.get("p95_availability_ms")),
        "database_health_failures": _as_int(row.get("database_health_failures")),
    }


def _query_product(resource_id: str, window: AzureWindow) -> dict[str, Any]:
    rows = _query_rows(resource_id, window, _PRODUCT_QUERY)
    surfaces: list[dict[str, Any]] = []
    coach: list[dict[str, Any]] = []
    for row in rows:
        if row.get("row_kind") == "surface":
            surfaces.append(
                {
                    "surface": _bounded_label(row.get("dimension"), limit=32),
                    "app_users": _as_int(row.get("app_users")),
                    "today_users": _as_int(row.get("today_users")),
                    "today_reach_rate": _as_float(row.get("today_reach_rate")),
                    "decision_prompts": _as_int(row.get("prompts")),
                    "decision_responses": _as_int(row.get("responses")),
                    "decision_response_rate": _as_float(row.get("response_rate")),
                    "reported_value_rate": _as_float(
                        row.get("reported_value_rate")
                    ),
                    "repeated_users": _as_int(row.get("repeated_users")),
                    "repeated_rate": _as_float(row.get("repeated_rate")),
                }
            )
        elif row.get("row_kind") == "coach":
            coach.append(
                {
                    "insight_type": _bounded_label(row.get("dimension"), limit=48),
                    "useful_votes": _as_int(row.get("up")),
                    "total_votes": _as_int(row.get("total")),
                    "useful_rate": _as_float(row.get("useful_rate")),
                }
            )
    return {"surfaces": surfaces, "coach": coach}


def _query_platform(resource_id: str, window: AzureWindow) -> dict[str, Any]:
    rows = _query_rows(resource_id, window, _PLATFORM_QUERY)
    sync: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    connections: list[dict[str, Any]] = []
    systemic_affected_users = 0
    for row in rows:
        row_kind = row.get("row_kind")
        if row_kind == "sync":
            sync.append(
                {
                    "platform": _bounded_label(row.get("platform"), limit=32),
                    "attempts": _as_int(row.get("attempts")),
                    "successes": _as_int(row.get("successes")),
                    "failures": _as_int(row.get("failures")),
                    "failure_rate": _as_float(row.get("failure_rate")),
                }
            )
        elif row_kind == "failure_total":
            systemic_affected_users = _as_int(row.get("affected_users"))
        elif row_kind == "failure":
            failures.append(
                {
                    "platform": _bounded_label(row.get("platform"), limit=32),
                    "failure_class": _bounded_label(
                        row.get("failure_class"),
                        limit=48,
                    ),
                    "failures": _as_int(row.get("failures")),
                    "affected_users": _as_int(row.get("affected_users")),
                }
            )
        elif row_kind == "connection":
            connections.append(
                {
                    "platform": _bounded_label(row.get("platform"), limit=32),
                    "flow": _bounded_label(row.get("flow"), limit=32),
                    "stage": _bounded_label(row.get("stage"), limit=32),
                    "outcome": _bounded_label(row.get("outcome"), limit=32),
                    "attempts": _as_int(row.get("attempts")),
                }
            )
    return {
        "sync": sync,
        "systemic_affected_users": systemic_affected_users,
        "systemic_failures": failures,
        "connections": connections,
    }


def _arm_get(
    url: str,
    *,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    token = _credential().get_token("https://management.azure.com/.default").token
    headers = {"Authorization": f"Bearer {token}"}
    client = _arm_client()
    for attempt in range(2):
        response = client.get(url, params=params, headers=headers)
        if response.status_code not in {408, 429, 500, 502, 503, 504} or attempt == 1:
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise AzureMonitorQueryError(
                    "azure_query_failed",
                    "Azure Alerts Management returned a non-object response",
                )
            return payload

        retry_after = response.headers.get("Retry-After", "")
        delay = min(float(retry_after), 2.0) if retry_after.isdigit() else 0.5
        time.sleep(delay)

    raise AzureMonitorQueryError(
        "azure_query_failed",
        "Azure Alerts Management retry budget exhausted",
    )


def _list_alert_items(
    url: str,
    *,
    params: dict[str, str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    next_url: str | None = url
    next_params: dict[str, str] | None = params
    for _ in range(3):
        if next_url is None:
            break
        payload = _arm_get(next_url, params=next_params)
        raw_items = payload.get("value", [])
        if not isinstance(raw_items, list):
            raise AzureMonitorQueryError(
                "azure_query_failed",
                "Azure Alerts Management returned an invalid value collection",
            )
        items.extend(item for item in raw_items if isinstance(item, dict))

        raw_next = payload.get("nextLink")
        if not raw_next:
            next_url = None
            continue
        parsed = urlparse(str(raw_next))
        try:
            continuation_port = parsed.port
        except ValueError:
            continuation_port = -1
        if (
            parsed.scheme.lower() != "https"
            or (parsed.hostname or "").lower() != "management.azure.com"
            or parsed.username is not None
            or parsed.password is not None
            or continuation_port not in (None, 443)
        ):
            raise AzureMonitorQueryError(
                "azure_query_failed",
                "Azure Alerts Management returned an invalid continuation URL",
            )
        next_url = str(raw_next)
        next_params = None

    if next_url is not None:
        raise AzureMonitorQueryError(
            "azure_query_partial",
            "Azure Alerts Management exceeded the bounded page limit",
        )
    return items


def _alert_identity(item: dict[str, Any]) -> tuple[str, ...]:
    alert_id = item.get("id")
    if isinstance(alert_id, str) and alert_id:
        return ("id", alert_id.lower())

    properties = item.get("properties")
    essentials = properties.get("essentials") if isinstance(properties, dict) else None
    if not isinstance(essentials, dict):
        return ("unknown", repr(sorted(item.items())))
    return (
        "fallback",
        _bounded_label(essentials.get("alertRule"), limit=256),
        _bounded_label(essentials.get("startDateTime"), limit=40),
        _bounded_label(essentials.get("lastModifiedDateTime"), limit=40),
    )


def _query_alerts(resource_id: str, window: AzureWindow) -> dict[str, Any]:
    start = datetime.now(timezone.utc) - _WINDOWS[window]
    end = datetime.now(timezone.utc)
    custom_range = (
        f"{start.isoformat(timespec='seconds').replace('+00:00', 'Z')}/"
        f"{end.isoformat(timespec='seconds').replace('+00:00', 'Z')}"
    )
    url = (
        f"https://management.azure.com{resource_id}"
        "/providers/Microsoft.AlertsManagement/alerts"
    )
    base_params = {
        "api-version": "2019-03-01",
        "targetResource": resource_id,
        "includeContext": "false",
        "includeEgressConfig": "false",
        "pageCount": "100",
        "sortBy": "lastModifiedDateTime",
        "sortOrder": "desc",
        "select": (
            "severity,alertState,monitorCondition,alertRule,startDateTime,"
            "lastModifiedDateTime,monitorConditionResolvedDateTime"
        ),
    }
    current_items = _list_alert_items(
        url,
        params={
            **base_params,
            # Alert instances are retained for at most 30 days. Query that full
            # retention window so an alert fired before the selected history
            # window cannot produce a false-clear console state.
            "timeRange": "30d",
            "monitorCondition": "Fired",
        },
    )
    history_items = _list_alert_items(
        url,
        params={**base_params, "customTimeRange": custom_range},
    )
    seen: set[tuple[str, ...]] = set()
    items = []
    for item in (*current_items, *history_items):
        identity = _alert_identity(item)
        if identity in seen:
            continue
        seen.add(identity)
        items.append(item)

    severity_counts = {f"sev{level}": 0 for level in range(5)}
    state_counts = {"new": 0, "acknowledged": 0, "closed": 0}
    rules: dict[str, dict[str, Any]] = {}
    total = 0
    firing = 0
    resolved = 0

    for item in items:
        properties = item.get("properties")
        if not isinstance(properties, dict):
            continue
        essentials = properties.get("essentials")
        if not isinstance(essentials, dict):
            continue
        total += 1

        severity = _bounded_label(essentials.get("severity"), limit=8)
        severity_key = severity.lower()
        if severity_key in severity_counts:
            severity_counts[severity_key] += 1

        state = _bounded_label(essentials.get("alertState"), limit=24).lower()
        if state in state_counts:
            state_counts[state] += 1

        condition = _bounded_label(
            essentials.get("monitorCondition"),
            limit=24,
        )
        if condition.lower() == "fired":
            firing += 1
        elif condition.lower() == "resolved":
            resolved += 1

        rule = _alert_rule_label(essentials.get("alertRule"))
        changed_at = _bounded_label(
            essentials.get("lastModifiedDateTime")
            or essentials.get("monitorConditionResolvedDateTime")
            or essentials.get("startDateTime"),
            fallback="",
            limit=40,
        )
        summary = rules.setdefault(
            rule,
            {
                "rule": rule,
                "severity": severity if severity_key in severity_counts else "unknown",
                "firing": 0,
                "resolved": 0,
                "last_changed_at": None,
            },
        )
        if condition.lower() == "fired":
            summary["firing"] += 1
        elif condition.lower() == "resolved":
            summary["resolved"] += 1
        if changed_at and (
            summary["last_changed_at"] is None
            or changed_at > summary["last_changed_at"]
        ):
            summary["last_changed_at"] = changed_at

    rule_summaries = sorted(
        rules.values(),
        key=lambda value: (
            int(value["firing"]),
            value["last_changed_at"] or "",
        ),
        reverse=True,
    )[:8]
    return {
        "total": total,
        "firing": firing,
        "resolved": resolved,
        "severity": severity_counts,
        "states": state_counts,
        "rules": rule_summaries,
    }


def _query_section(
    section: str,
    resource_id: str,
    window: AzureWindow,
) -> dict[str, Any]:
    loaders: dict[str, Callable[[str, AzureWindow], dict[str, Any]]] = {
        "alerts": _query_alerts,
        "service": _query_service,
        "product": _query_product,
        "platform": _query_platform,
    }
    return loaders[section](resource_id, window)


def _cache_key(section: str, resource_id: str, window: AzureWindow) -> tuple[str, str, str, str]:
    return section, resource_id.lower(), window, _QUERY_VERSION


def _section_lock(key: tuple[str, str, str, str]) -> threading.Lock:
    with _STATE_LOCK:
        return _LOCKS.setdefault(key, threading.Lock())


def _failure_reason(exc: BaseException) -> AzureReason:
    if isinstance(exc, AzureMonitorQueryError):
        return exc.reason
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "azure_query_timed_out"
    return "azure_query_failed"


def _fallback_snapshot(
    key: tuple[str, str, str, str],
    section: str,
    reason: AzureReason,
    now: float,
) -> AzureSectionSnapshot:
    with _STATE_LOCK:
        entry = _CACHE.get(key)
    if entry is not None and now - entry.cached_at <= _STALE_LIMIT_SECONDS[section]:
        return AzureSectionSnapshot(
            freshness="stale",
            as_of=entry.as_of,
            reason=reason,
            data=entry.data,
        )
    return AzureSectionSnapshot(
        freshness="unavailable",
        as_of=None,
        reason=reason,
        data=None,
    )


def _get_section(
    section: str,
    resource_id: str,
    window: AzureWindow,
) -> AzureSectionSnapshot:
    key = _cache_key(section, resource_id, window)
    now = time.monotonic()
    with _STATE_LOCK:
        entry = _CACHE.get(key)
        failure = _FAILURES.get(key)
    if entry is not None and now - entry.cached_at <= _FRESH_TTL_SECONDS:
        return AzureSectionSnapshot(
            freshness="fresh",
            as_of=entry.as_of,
            reason=None,
            data=entry.data,
        )
    if failure is not None and now - failure[0] <= _NEGATIVE_TTL_SECONDS:
        return _fallback_snapshot(key, section, failure[1], now)

    lock = _section_lock(key)
    with lock:
        now = time.monotonic()
        with _STATE_LOCK:
            entry = _CACHE.get(key)
            failure = _FAILURES.get(key)
        if entry is not None and now - entry.cached_at <= _FRESH_TTL_SECONDS:
            return AzureSectionSnapshot(
                freshness="fresh",
                as_of=entry.as_of,
                reason=None,
                data=entry.data,
            )
        if failure is not None and now - failure[0] <= _NEGATIVE_TTL_SECONDS:
            return _fallback_snapshot(key, section, failure[1], now)

        try:
            data = _query_section(section, resource_id, window)
        except (
            AzureMonitorQueryError,
            AzureError,
            httpx.HTTPError,
            TimeoutError,
            ImportError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            reason = _failure_reason(exc)
            logger.warning(
                "admin Azure Monitor %s refresh failed: %s",
                section,
                exc,
                exc_info=True,
            )
            failed_at = time.monotonic()
            with _STATE_LOCK:
                _FAILURES[key] = (failed_at, reason)
            return _fallback_snapshot(key, section, reason, failed_at)

        as_of = datetime.now(timezone.utc)
        completed_at = time.monotonic()
        fresh_entry = _CacheEntry(data=data, as_of=as_of, cached_at=completed_at)
        with _STATE_LOCK:
            _CACHE[key] = fresh_entry
            _FAILURES.pop(key, None)
        return AzureSectionSnapshot(
            freshness="fresh",
            as_of=as_of,
            reason=None,
            data=data,
        )


def _clear_in_flight(
    key: tuple[str, str, str, str],
    future: Future[AzureSectionSnapshot],
) -> None:
    with _STATE_LOCK:
        if _IN_FLIGHT.get(key) is future:
            _IN_FLIGHT.pop(key, None)


def _submit_section(
    section: str,
    resource_id: str,
    window: AzureWindow,
) -> Future[AzureSectionSnapshot]:
    key = _cache_key(section, resource_id, window)
    with _STATE_LOCK:
        existing = _IN_FLIGHT.get(key)
        if existing is not None:
            return existing
        future = _EXECUTOR.submit(_get_section, section, resource_id, window)
        _IN_FLIGHT[key] = future
    future.add_done_callback(lambda completed: _clear_in_flight(key, completed))
    return future


def get_ops_telemetry(window: AzureWindow) -> dict[str, AzureSectionSnapshot]:
    """Return independently cached Azure sections for one allowlisted window.

    Product value uses a fixed 28-day view so repeated weekly use has a
    meaningful denominator; operational sections follow the selected window.
    """
    if window not in _WINDOWS:
        raise ValueError(f"Unsupported Azure operations window: {window}")

    try:
        resource_id = _configured_resource_id()
    except ValueError:
        logger.error("%s is invalid", _RESOURCE_ENV, exc_info=True)
        resource_id = None
    if resource_id is None:
        unavailable = AzureSectionSnapshot(
            freshness="unavailable",
            as_of=None,
            reason="azure_telemetry_not_configured",
            data=None,
        )
        return {section: unavailable for section in _SECTION_NAMES}

    section_windows: dict[str, AzureWindow] = {
        section: "28d" if section == "product" else window
        for section in _SECTION_NAMES
    }
    futures = {
        section: _submit_section(
            section,
            resource_id,
            section_windows[section],
        )
        for section in _SECTION_NAMES
    }
    done, _ = wait(futures.values(), timeout=_TOTAL_DEADLINE_SECONDS)
    results: dict[str, AzureSectionSnapshot] = {}
    now = time.monotonic()
    for section, future in futures.items():
        if future in done:
            results[section] = future.result()
            continue
        results[section] = _fallback_snapshot(
            _cache_key(section, resource_id, section_windows[section]),
            section,
            "azure_query_timed_out",
            now,
        )
    return results


def azure_portal_links() -> tuple[str, str]:
    """Return Azure portal links without exposing arbitrary browser-controlled URLs."""
    alerts = (
        "https://portal.azure.com/#view/"
        "Microsoft_Azure_Monitoring/AzureMonitoringBrowseBlade/~/alertsV2"
    )
    try:
        resource_id = _configured_resource_id()
    except ValueError:
        resource_id = None
    logs = (
        f"https://portal.azure.com/#resource{resource_id}/logs"
        if resource_id
        else "https://portal.azure.com/#view/Microsoft_Azure_Monitoring/AzureMonitoringBrowseBlade/~/logs"
    )
    return alerts, logs


def _reset_cache_for_tests() -> None:
    """Clear process-local clients and snapshots for deterministic tests."""
    with _STATE_LOCK:
        _CACHE.clear()
        _FAILURES.clear()
        _LOCKS.clear()
        _IN_FLIGHT.clear()
    _credential.cache_clear()
    if hasattr(_logs_client, "cache_clear"):
        _logs_client.cache_clear()
    if hasattr(_arm_client, "cache_info") and _arm_client.cache_info().currsize:
        _arm_client().close()
    if hasattr(_arm_client, "cache_clear"):
        _arm_client.cache_clear()
