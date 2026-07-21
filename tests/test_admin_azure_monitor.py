"""Unit tests for the trusted Azure Monitor admin adapter."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from threading import Event
from types import SimpleNamespace

import pytest
from azure.monitor.query import LogsQueryStatus

from api import admin_azure_monitor as monitor


RESOURCE_ID = (
    "/subscriptions/11111111-1111-1111-1111-111111111111/"
    "resourceGroups/rg-trainsight/providers/Microsoft.Insights/"
    "components/appi-praxys-backend"
)


@pytest.fixture(autouse=True)
def reset_monitor(monkeypatch):
    monkeypatch.delenv("PRAXYS_BACKEND_APPINSIGHTS_RESOURCE_ID", raising=False)
    monitor._reset_cache_for_tests()
    yield
    monitor._reset_cache_for_tests()


def test_unconfigured_adapter_is_explicitly_unavailable() -> None:
    snapshots = monitor.get_ops_telemetry("24h")

    assert set(snapshots) == {"alerts", "service", "product", "platform"}
    assert all(item.freshness == "unavailable" for item in snapshots.values())
    assert all(
        item.reason == "azure_telemetry_not_configured"
        for item in snapshots.values()
    )
    assert all(item.data is None for item in snapshots.values())


def test_resource_id_must_be_backend_application_insights(monkeypatch) -> None:
    monkeypatch.setenv(
        "PRAXYS_BACKEND_APPINSIGHTS_RESOURCE_ID",
        "/subscriptions/11111111-1111-1111-1111-111111111111/"
        "resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/not-allowed",
    )

    snapshots = monitor.get_ops_telemetry("7d")

    assert all(item.freshness == "unavailable" for item in snapshots.values())
    assert all(
        item.reason == "azure_telemetry_not_configured"
        for item in snapshots.values()
    )


def test_section_results_are_cached_per_window(monkeypatch) -> None:
    monkeypatch.setenv("PRAXYS_BACKEND_APPINSIGHTS_RESOURCE_ID", RESOURCE_ID)
    calls: list[tuple[str, str]] = []

    def fake_query(section: str, resource_id: str, window: str) -> dict:
        assert resource_id == RESOURCE_ID
        calls.append((section, window))
        return {"section": section, "window": window}

    monkeypatch.setattr(monitor, "_query_section", fake_query)

    first = monitor.get_ops_telemetry("24h")
    second = monitor.get_ops_telemetry("24h")

    assert len(calls) == 4
    assert ("product", "28d") in calls
    assert all(item.freshness == "fresh" for item in first.values())
    assert all(item.freshness == "fresh" for item in second.values())
    assert first["service"].data == {"section": "service", "window": "24h"}


def test_failed_refresh_serves_bounded_stale_value(monkeypatch) -> None:
    monkeypatch.setenv("PRAXYS_BACKEND_APPINSIGHTS_RESOURCE_ID", RESOURCE_ID)
    monkeypatch.setattr(
        monitor,
        "_query_section",
        lambda section, resource_id, window: {"requests": 12},
    )
    first = monitor._get_section("service", RESOURCE_ID, "24h")
    assert first.freshness == "fresh"

    key = monitor._cache_key("service", RESOURCE_ID, "24h")
    with monitor._STATE_LOCK:
        monitor._CACHE[key] = replace(
            monitor._CACHE[key],
            cached_at=monitor._CACHE[key].cached_at - monitor._FRESH_TTL_SECONDS - 1,
        )

    def fail_query(section: str, resource_id: str, window: str) -> dict:
        raise monitor.AzureMonitorQueryError(
            "azure_query_failed",
            "synthetic Azure failure",
        )

    monkeypatch.setattr(monitor, "_query_section", fail_query)
    stale = monitor._get_section("service", RESOURCE_ID, "24h")

    assert stale.freshness == "stale"
    assert stale.reason == "azure_query_failed"
    assert stale.data == {"requests": 12}
    assert stale.as_of == first.as_of


def test_concurrent_failed_refresh_uses_negative_cache(monkeypatch) -> None:
    monkeypatch.setenv("PRAXYS_BACKEND_APPINSIGHTS_RESOURCE_ID", RESOURCE_ID)
    started = Event()
    release = Event()
    calls = 0

    def fail_query(section: str, resource_id: str, window: str) -> dict:
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(timeout=2)
        raise monitor.AzureMonitorQueryError(
            "azure_query_failed",
            "synthetic Azure failure",
        )

    monkeypatch.setattr(monitor, "_query_section", fail_query)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(
            monitor._get_section,
            "service",
            RESOURCE_ID,
            "24h",
        )
        assert started.wait(timeout=2)
        second = executor.submit(
            monitor._get_section,
            "service",
            RESOURCE_ID,
            "24h",
        )
        release.set()
        assert first.result().freshness == "unavailable"
        assert second.result().freshness == "unavailable"

    assert calls == 1


def test_same_key_requests_share_one_executor_future(monkeypatch) -> None:
    started = Event()
    release = Event()
    calls = 0

    def slow_query(section: str, resource_id: str, window: str) -> dict:
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(timeout=2)
        return {"requests": 12}

    monkeypatch.setattr(monitor, "_query_section", slow_query)
    first = monitor._submit_section("service", RESOURCE_ID, "24h")
    assert started.wait(timeout=2)
    waiters = [
        monitor._submit_section("service", RESOURCE_ID, "24h")
        for _ in range(8)
    ]

    assert all(waiter is first for waiter in waiters)
    assert len(monitor._IN_FLIGHT) == 1

    release.set()
    assert first.result(timeout=2).freshness == "fresh"
    assert calls == 1


def test_logs_query_rejects_partial_results(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def query_resource(self, resource_id, query, **kwargs):
            captured.update(
                resource_id=resource_id,
                query=query,
                kwargs=kwargs,
            )
            return SimpleNamespace(status=LogsQueryStatus.PARTIAL, tables=[])

    monkeypatch.setattr(monitor, "_logs_client", lambda: FakeClient())

    with pytest.raises(monitor.AzureMonitorQueryError) as exc:
        monitor._query_rows(RESOURCE_ID, "7d", "print rid='__RESOURCE_ID__'")

    assert exc.value.reason == "azure_query_partial"
    assert captured["resource_id"] == RESOURCE_ID
    assert RESOURCE_ID.lower() in str(captured["query"])
    assert captured["kwargs"]["server_timeout"] == 8


def test_queries_use_application_insights_resource_schema() -> None:
    combined = "\n".join(
        (monitor._SERVICE_QUERY, monitor._PRODUCT_QUERY, monitor._PLATFORM_QUERY)
    )

    assert "AppRequests" not in combined
    assert "AppEvents" not in combined
    assert "AppMetrics" not in combined
    assert "requests" in monitor._SERVICE_QUERY
    assert "availabilityResults" in monitor._SERVICE_QUERY
    assert "customEvents" in combined
    assert "customMetrics" in combined
    assert "customDimensions" in combined
    assert "dcountif" not in monitor._PRODUCT_QUERY
    assert "bin(timestamp, 15m)" in monitor._PLATFORM_QUERY
    assert "cluster_users >= 5" in monitor._PLATFORM_QUERY
    assert "by cluster_start, platform\n" in monitor._PLATFORM_QUERY
    assert "by cluster_start, platform, failure_class" not in monitor._PLATFORM_QUERY


def test_product_and_platform_rows_are_aggregate_only(monkeypatch) -> None:
    product_rows = [
        {
            "row_kind": "surface",
            "dimension": "web",
            "app_users": 10,
            "today_users": 8,
            "today_reach_rate": 0.8,
            "prompts": 6,
            "responses": 4,
            "response_rate": 2 / 3,
            "reported_value_rate": 0.75,
            "repeated_users": 5,
            "repeated_rate": 0.625,
        },
        {
            "row_kind": "coach",
            "dimension": "daily_brief",
            "up": 7,
            "total": 9,
            "useful_rate": 7 / 9,
        },
    ]
    platform_rows = [
        {
            "row_kind": "failure_total",
            "failures": 3,
            "affected_users": 3,
        },
        {
            "row_kind": "sync",
            "platform": "garmin",
            "attempts": 20,
            "successes": 17,
            "failures": 3,
            "failure_rate": 0.15,
        },
        {
            "row_kind": "failure",
            "platform": "garmin",
            "failure_class": "token_rejected",
            "failures": 3,
            "affected_users": 3,
        },
        {
            "row_kind": "connection",
            "platform": "garmin",
            "flow": "mfa",
            "stage": "mfa_verify",
            "outcome": "connected",
            "attempts": 4,
        },
    ]

    monkeypatch.setattr(
        monitor,
        "_query_rows",
        lambda resource_id, window, query: (
            product_rows if query == monitor._PRODUCT_QUERY else platform_rows
        ),
    )

    product = monitor._query_product(RESOURCE_ID, "28d")
    platform = monitor._query_platform(RESOURCE_ID, "28d")

    assert product["surfaces"][0]["today_reach_rate"] == 0.8
    assert product["coach"][0]["useful_votes"] == 7
    assert platform["sync"][0]["failures"] == 3
    assert platform["systemic_affected_users"] == 3
    assert platform["systemic_failures"][0]["affected_users"] == 3
    assert "user_id" not in repr(product)
    assert "user_id" not in repr(platform)


def test_alert_instances_are_aggregated_by_rule(monkeypatch) -> None:
    captured: list[tuple[str, dict[str, str]]] = []
    fired_item = {
        "id": "/alerts/fired",
        "properties": {
            "essentials": {
                "severity": "Sev2",
                "alertState": "New",
                "monitorCondition": "Fired",
                "alertRule": (
                    "/subscriptions/11111111-1111-1111-1111-111111111111/"
                    "resourceGroups/rg-trainsight/providers/Microsoft.Insights/"
                    "scheduledQueryRules/praxys-sync-systemic-failures"
                ),
                "startDateTime": "2026-06-19T01:00:00Z",
                "lastModifiedDateTime": "2026-07-19T01:01:00Z",
            }
        },
    }
    history_payload = {
        "value": [
            fired_item,
            {
                "id": "/alerts/resolved",
                "properties": {
                    "essentials": {
                        "severity": "Sev2",
                        "alertState": "Closed",
                        "monitorCondition": "Resolved",
                        "alertRule": "praxys-sync-systemic-failures",
                        "startDateTime": "2026-07-18T01:00:00Z",
                        "lastModifiedDateTime": "2026-07-18T01:05:00Z",
                    }
                }
            },
        ]
    }

    def fake_arm_get(url: str, *, params=None):
        captured.append((url, params))
        if params.get("monitorCondition") == "Fired":
            return {"value": [fired_item]}
        return history_payload

    monkeypatch.setattr(monitor, "_arm_get", fake_arm_get)
    result = monitor._query_alerts(RESOURCE_ID, "24h")

    assert result["total"] == 2
    assert result["firing"] == 1
    assert result["resolved"] == 1
    assert result["severity"]["sev2"] == 2
    assert result["rules"] == [
        {
            "rule": "praxys-sync-systemic-failures",
            "severity": "Sev2",
            "firing": 1,
            "resolved": 1,
            "last_changed_at": "2026-07-19T01:01:00Z",
        }
    ]
    assert len(captured) == 2
    current_url, current_params = captured[0]
    history_url, history_params = captured[1]
    assert current_params["targetResource"] == RESOURCE_ID
    assert current_params["includeContext"] == "false"
    assert current_params["timeRange"] == "30d"
    assert current_params["monitorCondition"] == "Fired"
    assert "customTimeRange" not in current_params
    assert "customTimeRange" in history_params
    assert current_url == history_url == (
        f"https://management.azure.com{RESOURCE_ID}"
        "/providers/Microsoft.AlertsManagement/alerts"
    )


def test_alert_pagination_reports_partial_after_bound(monkeypatch) -> None:
    calls = 0

    def fake_arm_get(url: str, *, params=None):
        nonlocal calls
        calls += 1
        return {
            "value": [],
            "nextLink": (
                "https://management.azure.com/subscriptions/next"
                f"?page={calls + 1}"
            ),
        }

    monkeypatch.setattr(monitor, "_arm_get", fake_arm_get)

    with pytest.raises(monitor.AzureMonitorQueryError) as exc:
        monitor._query_alerts(RESOURCE_ID, "28d")

    assert exc.value.reason == "azure_query_partial"
    assert calls == 3


def test_alert_pagination_accepts_default_https_port(monkeypatch) -> None:
    calls = 0

    def fake_arm_get(url: str, *, params=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return {
                "value": [],
                "nextLink": (
                    "https://management.azure.com:443/subscriptions/next?page=2"
                ),
            }
        return {"value": []}

    monkeypatch.setattr(monitor, "_arm_get", fake_arm_get)

    result = monitor._query_alerts(RESOURCE_ID, "24h")

    assert result["total"] == 0
    assert calls == 3


@pytest.mark.parametrize(
    "next_link",
    [
        "http://management.azure.com/subscriptions/next",
        "https://example.com/subscriptions/next",
        "https://user@management.azure.com/subscriptions/next",
        "https://management.azure.com:444/subscriptions/next",
    ],
)
def test_alert_pagination_rejects_untrusted_continuations(
    monkeypatch,
    next_link: str,
) -> None:
    monkeypatch.setattr(
        monitor,
        "_arm_get",
        lambda url, *, params=None: {"value": [], "nextLink": next_link},
    )

    with pytest.raises(monitor.AzureMonitorQueryError) as exc:
        monitor._query_alerts(RESOURCE_ID, "24h")

    assert exc.value.reason == "azure_query_failed"


def test_portal_links_use_only_validated_server_configuration(monkeypatch) -> None:
    monkeypatch.setenv("PRAXYS_BACKEND_APPINSIGHTS_RESOURCE_ID", RESOURCE_ID)

    alerts, logs = monitor.azure_portal_links()

    assert "alertsV2" in alerts
    assert RESOURCE_ID in logs
    assert datetime.now(timezone.utc).tzinfo is not None
