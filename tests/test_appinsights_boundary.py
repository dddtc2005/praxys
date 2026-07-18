"""Static contracts for the frontend/backend Application Insights boundary."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RESOURCE_MAP = ROOT / ".github" / "azure-observability.env"
BACKEND_WORKFLOW = ROOT / ".github" / "workflows" / "deploy-backend.yml"
FRONTEND_WORKFLOW = (
    ROOT / ".github" / "workflows" / "deploy-frontend-appservice.yml"
)
BOUNDARY_SCRIPT = ROOT / "scripts" / "appinsights_boundary.sh"


def _resource_names() -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in RESOURCE_MAP.read_text(encoding="utf-8").splitlines()
        if line
    )


def test_appinsights_resources_are_distinct() -> None:
    """Browser and backend telemetry must resolve to different components."""
    resources = _resource_names()

    assert resources["FRONTEND_APPINSIGHTS_NAME"]
    assert resources["BACKEND_APPINSIGHTS_NAME"]
    assert (
        resources["FRONTEND_APPINSIGHTS_NAME"]
        != resources["BACKEND_APPINSIGHTS_NAME"]
    )


def test_backend_workflow_enforces_server_only_ingestion() -> None:
    """The backend workflow owns routing and rejects local-auth drift."""
    workflow = BACKEND_WORKFLOW.read_text(encoding="utf-8")
    script = BOUNDARY_SCRIPT.read_text(encoding="utf-8")

    assert "vars.APPLICATIONINSIGHTS_CONNECTION_STRING" not in workflow
    assert "backend-preflight" in workflow
    assert "backend-cutover" in workflow
    assert "properties.DisableLocalAuth=true" in script
    assert "properties.WorkspaceResourceId" in script
    assert "Monitoring Metrics Publisher" in script
    assert "forged_browser_probe" in script
    assert "rollback_cutover" in script
    assert "rollback-to-frontend" in script
    assert "praxys-db-health-unhealthy" in script
    assert "wt-praxys-api-health" in script


def test_frontend_workflow_resolves_only_frontend_ingestion() -> None:
    """The browser build must never receive the backend connection string."""
    workflow = FRONTEND_WORKFLOW.read_text(encoding="utf-8")

    assert "vars.VITE_APPINSIGHTS_CONNECTION_STRING" not in workflow
    assert "frontend-resolve" in workflow


def test_boundary_script_has_valid_bash_syntax() -> None:
    """The deployment guard must remain parseable by the Actions Bash shell."""
    if os.name == "nt":
        pytest.skip("Windows resolves bash to WSL; Actions validation runs on Linux")
    subprocess.run(["bash", "-n", str(BOUNDARY_SCRIPT)], check=True)
