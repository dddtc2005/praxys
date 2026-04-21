# Deployment Guide

## Usage Modes

**Deployed cloud app + local CLI plugin (recommended for all users):**
- Web dashboard deployed on Azure (SWA + App Service)
- Users register, connect platforms, sync, and view dashboard in the browser
- CLI plugin (Claude Code / Copilot) connects to the deployed API via `PRAXYS_URL`
- AI features (training plans, insights) run through the CLI plugin's MCP tools
- Per-user data, encrypted credentials, background sync — all handled by the backend

**Fully local (development / personal use):**
- Backend + frontend run on localhost
- Same auth flow as cloud (register, login, JWT)
- First registered user becomes admin automatically
- Useful for development, personal training, or trying out the app

## Joining an Existing Deployment

If a Praxys instance is already deployed and you want to contribute as a developer, you do not need to deploy your own. Ask the project admin for:

1. **Access to the Azure resource group** (`rg-trainsight`) — Contributor role is sufficient for most development tasks
2. **An invitation code** — to register an account on the deployed instance
3. **Repository access** — clone the repo and follow [Local Development Setup](#local-development-setup) below for backend/frontend development

The deployed cloud instance and your local dev instance use the same codebase. You can develop locally and deploy via the existing CI/CD pipeline.

---

## Local Development Setup

### 1. Create `.env` from the example

```bash
cp .env.example .env
```

Edit `.env` and set at minimum:

```bash
# Required: encryption key for platform credentials
# Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
PRAXYS_LOCAL_ENCRYPTION_KEY=<your-generated-key>

# Optional: JWT secret (tokens won't survive restarts without this)
# Generate: python -c "import secrets; print(secrets.token_urlsafe(48))"
PRAXYS_JWT_SECRET=<your-generated-secret>

# Optional: admin email (registers without invitation, always admin)
# PRAXYS_ADMIN_EMAIL=you@example.com
```

### 2. Install dependencies and start servers

```bash
# Backend
pip install -r requirements.txt
python -m uvicorn api.main:app --reload

# Frontend (separate terminal)
cd web && npm install && npm run dev
```

The database (`data/trainsight.db`) is created automatically on first startup. New columns are added automatically via auto-migration — no manual migration steps needed.

### 3. Register and configure

1. Open the frontend (default: `http://localhost:5173`)
2. Register — the first user becomes admin automatically
3. Connect platforms via the Settings page
4. Trigger a sync

## Prerequisites (Azure)

- Azure subscription
- GitHub repository (dddtc2005/praxys)
- Azure CLI installed locally

## Azure Setup (One-Time)

### Resource Names

| Resource | Name |
|----------|------|
| Resource group | `rg-trainsight` |
| App Service | `trainsight-app` |
| Key Vault | `kv-trainsight` |
| Static Web App | `swa-trainsight` |

### 1. Resource Group

```bash
az group create --name rg-trainsight --location eastus
```

### 2. App Service Plan (Linux B1)

```bash
az appservice plan create \
  --name plan-trainsight \
  --resource-group rg-trainsight \
  --sku B1 \
  --is-linux
```

### 3. App Service (Python 3.12)

```bash
az webapp create \
  --name trainsight-app \
  --resource-group rg-trainsight \
  --plan plan-trainsight \
  --runtime "PYTHON:3.12"
```

### 4. Enable Managed Identity

```bash
az webapp identity assign \
  --name trainsight-app \
  --resource-group rg-trainsight
```

Save the `principalId` from the output for step 7.

### 5. Create Key Vault

```bash
az keyvault create \
  --name kv-trainsight \
  --resource-group rg-trainsight \
  --location eastus \
  --sku standard
```

### 6. Create RSA Key in Key Vault

```bash
az keyvault key create \
  --vault-name kv-trainsight \
  --name credential-encryption-key \
  --kty RSA \
  --size 2048
```

### 7. Grant App Service Key Vault Access

```bash
az role assignment create \
  --role "Key Vault Crypto User" \
  --assignee <principalId-from-step-4> \
  --scope $(az keyvault show --name kv-trainsight --query id -o tsv)
```

### 8. Create Static Web App

```bash
az staticwebapp create \
  --name swa-trainsight \
  --resource-group rg-trainsight \
  --source https://github.com/dddtc2005/praxys \
  --branch main \
  --app-location "web" \
  --output-location "dist"
```

### 9. Link SWA Backend to App Service

```bash
az staticwebapp backends link \
  --name swa-trainsight \
  --resource-group rg-trainsight \
  --backend-resource-id $(az webapp show --name trainsight-app --resource-group rg-trainsight --query id -o tsv)
```

### 10. Configure CORS on App Service

CORS is handled at the Azure platform level, not via FastAPI middleware. The backend detects when it is running on Azure App Service (via the `WEBSITE_SITE_NAME` environment variable) and skips adding CORS middleware, deferring to the platform configuration.

```bash
az webapp cors add \
  --name trainsight-app \
  --resource-group rg-trainsight \
  --allowed-origins "https://swa-trainsight.azurestaticapps.net"
```

For local development, FastAPI's `CORSMiddleware` is added automatically (allowing `localhost:5173`). This can be customized via the `PRAXYS_CORS_ORIGINS` environment variable.

## GitHub Configuration

### Secrets (OIDC Authentication)

The CI/CD workflows use OIDC (OpenID Connect) for passwordless Azure authentication. This requires a federated credential on an Azure AD app registration.

| Secret | Value |
|--------|-------|
| `AZURE_CLIENT_ID` | App registration client ID |
| `AZURE_TENANT_ID` | Azure AD tenant ID |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription ID |
| `AZURE_SWA_TOKEN` | Static Web App deployment token (from Azure Portal > SWA > Manage deployment token) |

**Setting up OIDC:**

```bash
# Create app registration
az ad app create --display-name trainsight-ci

# Create federated credential for GitHub Actions
az ad app federated-credential create \
  --id <app-object-id> \
  --parameters '{
    "name": "github-main",
    "issuer": "https://token.actions.githubusercontent.com",
    "subject": "repo:dddtc2005/praxys:ref:refs/heads/main",
    "audiences": ["api://AzureADTokenExchange"]
  }'

# Grant Contributor role on the resource group
az role assignment create \
  --role Contributor \
  --assignee <app-client-id> \
  --scope /subscriptions/<sub-id>/resourceGroups/rg-trainsight
```

The backend workflow (`.github/workflows/deploy-backend.yml`) requests `id-token: write` permission for OIDC and uses `azure/login@v2` with the three OIDC secrets.

## App Service Environment Variables

Set via Azure Portal > App Service > Configuration > Application settings:

| Variable | Value | Notes |
|----------|-------|-------|
| `DATA_DIR` | `/home/data` | Persistent storage path |
| `PRAXYS_JWT_SECRET` | (random 32+ char string) | JWT signing key |
| `KEY_VAULT_URL` | `https://kv-trainsight.vault.azure.net/` | Key Vault URI |
| `KEY_VAULT_KEY_NAME` | `credential-encryption-key` | RSA key name |

Platform credentials (Garmin, Stryd, Oura) are entered by each user via the Settings page and stored encrypted in the database — no environment variables needed for those.

## Auto-Migration

The database schema is managed by `db/session.py:init_db()`. On every startup:
1. `Base.metadata.create_all()` creates any new tables
2. A lightweight migration step inspects existing tables for missing columns and runs `ALTER TABLE ... ADD COLUMN` as needed

This means deploying a new version with additional model columns just works — no manual migration steps required. The migration list is maintained in `init_db()`.

## Post-Deploy Steps

1. **Register first user** — `POST /api/auth/register` with email + password (becomes admin)
2. **Connect platforms** — via Settings page (credentials stored encrypted in DB via Key Vault)
3. **Trigger first sync** — via Settings page or `POST /api/sync` (authenticated)

## CI/CD Workflows

- **Backend** (`.github/workflows/deploy-backend.yml`) — triggers on changes to `api/`, `analysis/`, `sync/`, `db/`, `data/science/`, `tests/`, `requirements.txt`. Runs tests first, then deploys via OIDC to `trainsight-app`.
- **Frontend** (`.github/workflows/deploy-frontend.yml`) — triggers on changes to `web/`; PR builds create staging environments.

Background sync is handled by the backend scheduler (enabled by default; disable with `PRAXYS_SYNC_SCHEDULER=false`) — no CI job needed.

## CLI Plugin Setup

After deploying, users connect their CLI tools to the deployed backend:

```bash
# Register the local marketplace (one-time)
claude plugin marketplace add ./plugins/marketplace.json

# Install the plugin
claude plugin install trainsight

# The MCP server's PRAXYS_URL env var (in .mcp.json) routes
# requests to the deployed API with JWT authentication.
```

Users authenticate via `~/.trainsight/token` (cached JWT from login).
