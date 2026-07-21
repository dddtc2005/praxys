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
    assert "enableLogAccessUsingOnlyResourcePermissions" in script
    assert "actions: read" in workflow
    assert "Wait for compatible frontend deployment" in workflow
    assert "deploy-frontend-appservice.yml/runs" in workflow
    assert "git merge-base --is-ancestor" in workflow
    assert "git log --first-parent" in workflow
    assert "-f event=push" not in workflow
    assert "--paginate" in workflow
    assert "--slurp" in workflow
    assert 'select(.status != "completed")' in workflow
    assert "praxys-frontend.azurewebsites.net/healthz" in workflow
    assert ".deployed_sha" in workflow
    assert "Deployed frontend commit is not yet compatible" in workflow
    assert "Wait for App Service deployment endpoint to settle" in workflow
    assert "sleep 90" in workflow
    assert "az webapp log deployment list" in workflow
    assert "stable_probes >= 3" in workflow
    assert "timeout-minutes: 8" in workflow
    assert "timeout 20s az webapp" in workflow
    assert "group: deploy-backend-production" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "Monitoring Metrics Publisher" in script
    assert "Monitoring Reader" in script
    assert "userAssignedIdentities" in script
    assert "[?name=='AZURE_CLIENT_ID'].value | [0]" in script
    assert "PRAXYS_BACKEND_APPINSIGHTS_RESOURCE_ID" in script
    assert "--setting-names PRAXYS_BACKEND_APPINSIGHTS_RESOURCE_ID" in script
    assert "forged_browser_probe" in script
    assert "rollback_cutover" in script
    assert "rollback-to-frontend" in script
    assert "recreate_scheduled_alert" in script
    assert "del(.createdWithApiVersion)" in script
    assert "praxys-db-health-unhealthy" in script
    assert "wt-praxys-api-health" in script
    cutover = script.split("telemetry_cutover()", 1)[1]
    backend_branch, frontend_branch = cutover.split("frontend)", 1)
    frontend_branch = frontend_branch.split(";;", 1)[0]
    assert "verify_resource_context_access" in backend_branch
    assert "verify_resource_context_access" not in frontend_branch


def test_frontend_workflow_resolves_only_frontend_ingestion() -> None:
    """The browser build must never receive the backend connection string."""
    workflow = FRONTEND_WORKFLOW.read_text(encoding="utf-8")

    assert "vars.VITE_APPINSIGHTS_CONNECTION_STRING" not in workflow
    assert "frontend-resolve" in workflow
    assert "_deployed_sha.txt" in workflow
    assert 'printf \'%s\\n\' "${GITHUB_SHA}"' in workflow
    assert "group: deploy-frontend-production" in workflow
    assert "cancel-in-progress: false" in workflow


def test_boundary_script_has_valid_bash_syntax() -> None:
    """The deployment guard must remain parseable by the Actions Bash shell."""
    if os.name == "nt":
        pytest.skip("Windows resolves bash to WSL; Actions validation runs on Linux")
    subprocess.run(["bash", "-n", str(BOUNDARY_SCRIPT)], check=True)
