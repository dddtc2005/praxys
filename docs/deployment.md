# Deployment Guide

## Usage Modes

**Deployed cloud app + local CLI plugin (recommended for all users):**
- Web dashboard deployed on Azure (SWA + App Service)
- Users register, connect platforms, sync, and view dashboard in the browser
- CLI plugin (Claude Code / Copilot) connects to the deployed API via `TRAINSIGHT_URL`
- AI features (training plans, insights) run through the CLI plugin's MCP tools
- Per-user data, encrypted credentials, background sync — all handled by the backend

**Fully local (development / personal use):**
- Backend + frontend run on localhost
- Same auth flow as cloud (register, login, JWT)
- First registered user becomes admin automatically
- Useful for development, personal training, or trying out the app

## Prerequisites

- Azure subscription
- GitHub repository (dddtc2005/trainsight)
- Azure CLI installed locally

## Azure Setup (One-Time)

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
  --name <app-service-name> \
  --resource-group rg-trainsight \
  --plan plan-trainsight \
  --runtime "PYTHON:3.12"
```

### 4. Enable Managed Identity

```bash
az webapp identity assign \
  --name <app-service-name> \
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
  --source https://github.com/dddtc2005/trainsight \
  --branch main \
  --app-location "web" \
  --output-location "dist"
```

### 9. Link SWA Backend to App Service

```bash
az staticwebapp backends link \
  --name swa-trainsight \
  --resource-group rg-trainsight \
  --backend-resource-id $(az webapp show --name <app-service-name> --resource-group rg-trainsight --query id -o tsv)
```

## GitHub Configuration

### Secrets

| Secret | Value |
|--------|-------|
| `AZURE_CREDENTIALS` | Service principal JSON (`az ad sp create-for-rbac --sdk-auth`) |
| `AZURE_SWA_TOKEN` | Static Web App deployment token (from Azure Portal > SWA > Manage deployment token) |

### Variables

| Variable | Value |
|----------|-------|
| `AZURE_APP_SERVICE_NAME` | App Service name (e.g., `app-trainsight`) |

## App Service Environment Variables

Set via Azure Portal > App Service > Configuration > Application settings:

| Variable | Value | Notes |
|----------|-------|-------|
| `DATA_DIR` | `/home/data` | Persistent storage path |
| `TRAINSIGHT_JWT_SECRET` | (random 32+ char string) | JWT signing key |
| `KEY_VAULT_URL` | `https://kv-trainsight.vault.azure.net/` | Key Vault URI |
| `KEY_VAULT_KEY_NAME` | `credential-encryption-key` | RSA key name |
| `GARMIN_EMAIL` | (email) | Migration only -- later stored encrypted in DB |
| `GARMIN_PASSWORD` | (password) | Migration only -- later stored encrypted in DB |
| `STRYD_EMAIL` | (email) | Migration only |
| `STRYD_PASSWORD` | (password) | Migration only |
| `OURA_PAT` | (token) | Migration only |

## Post-Deploy Steps

1. **Register first user** -- `POST /api/auth/register` with email + password
2. **Run data migration** -- if migrating from local CSVs, use the migration endpoint or script
3. **Connect platforms** -- via Settings page (credentials stored encrypted in DB via Key Vault)
4. **Trigger first sync** -- via Settings page or `POST /api/sync` (authenticated)

## CI/CD Workflows

- **Backend** (`.github/workflows/deploy-backend.yml`) -- triggers on changes to `api/`, `analysis/`, `sync/`, `scripts/`, `db/`, `data/science/`, `requirements.txt`, `alembic.ini`
- **Frontend** (`.github/workflows/deploy-frontend.yml`) -- triggers on changes to `web/`; PR builds create staging environments

Background sync is handled by the backend scheduler (per-user, every 6 hours) -- no CI job needed.

## CLI Plugin Setup

After deploying, users connect their CLI tools to the deployed backend:

```bash
# Set the deployed backend URL
export TRAINSIGHT_URL=https://<app-service-name>.azurewebsites.net

# Install the plugin
claude plugin add ./plugins/trainsight

# The MCP tools auto-detect remote mode and use the deployed API
```

Users authenticate via `~/.trainsight/token` (cached JWT from login).
