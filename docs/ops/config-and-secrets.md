# Configuration & secrets

> **Summary:** Every Praxys config value, **where it is set** (the source of
> truth), what consumes it, and how to rotate it.
> **Use when:** Adding/changing/rotating an env var, secret, or build variable —
> or debugging "I changed a setting in the portal and it reverted".

## The golden rule

The backend's App Service **application settings are owned by the deploy
workflow**, not the portal. `.github/workflows/deploy-backend.yml` → *Sync App
Service settings* runs `az webapp config appsettings set` on **every deploy**
with a fixed list sourced from GitHub Actions secrets/variables (plus a few
literals). The Application Insights routing string is the deliberate exception
to the GitHub-value source: the workflow resolves it directly from the
backend-only Azure component. **Editing these keys in the Azure Portal is
transient — the next deploy overwrites them.**

## Where each thing lives

### GitHub Actions → Secrets
`Repo → Settings → Secrets and variables → Actions → Secrets`

| Secret | Purpose | Consumed by |
|---|---|---|
| `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` | OIDC login to Azure for deploys (no client secret). Agentic Workflow sources pin the same non-secret identity IDs directly because gh-aw's OIDC engine requires compile-time values. | deploy workflows |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription targeted by deployment workflows | deploy workflows |
| `PRAXYS_JWT_SECRET` | JWT signing key | pushed to App Service setting by `deploy-backend.yml` |
| `PRAXYS_DATABASE_URL` | Postgres DSN (#360). May carry the DB password unless Entra auth is used. **Optional** until cutover; empty = SQLite. | App Service setting (backend) |
| `WECHAT_MINIAPP_APPID` / `WECHAT_MINIAPP_SECRET` | WeChat Mini Program auth | App Service setting (backend) |
| `PRAXYS_SMTP_PASSWORD` | SMTP client authorization code (WeCom/Exmail) for verification + invitation emails. **Optional.** | App Service setting (backend) |
| `WECHAT_MINIAPP_UPLOAD_KEY` | Mini program CI upload key | `miniapp-publish.yml` |
| `COPILOT_ASSIGN_TOKEN` | **Required for workflow auto-assign** — fine-grained PAT (*Issues: write*, this repo only, with expiry). Agent assignment needs a user token; the built-in `GITHUB_TOKEN` is forbidden (issue #400). Manual UI assignment doesn't need it. | `assign-copilot.yml` |

### GitHub Actions → Variables
`… → Variables` (non-secret; build variables are inlined into the SPA and ship to browsers)

| Variable | Purpose | Consumed by |
|---|---|---|
| `VITE_API_URL` (`https://api.praxys.run`) | API base baked into the SPA | `deploy-frontend-appservice.yml` build |
| `AZURE_AI_ENDPOINT` | Azure OpenAI endpoint for insights, triage, i18n, and Agentic Workflows. Keep the trailing `/`; the agent workflows append `openai/v1`. | App Service setting + `i18n.yml` + Agentic Workflow `.md` sources |
| `KEY_VAULT_URL` / `KEY_VAULT_KEY_NAME` | Key Vault + RSA key name | App Service setting |
| `PRAXYS_FEEDBACK_BLOB_ACCOUNT_URL` (`https://stperftrainsight.blob.core.windows.net`) | Private Blob store for feedback screenshots (keyless via MI) | App Service setting (backend) |
| `PRAXYS_FEEDBACK_BLOB_CONTAINER` (`feedback-screenshots`) | Blob container for screenshots | App Service setting (backend) |
| `PRAXYS_SMTP_HOST` / `PRAXYS_SMTP_PORT` / `PRAXYS_SMTP_USER` / `PRAXYS_SMTP_FROM` / `PRAXYS_SMTP_STARTTLS` | SMTP transport for verification + invitation emails (non-secret; the password is the secret above). **Optional.** | App Service setting (backend) |
| `PRAXYS_APP_BASE_URL` (`https://praxys.run`) | Public origin for verify/invite links in those emails | App Service setting (backend) |
| `PRAXYS_DB_AUTH` (`entra` or unset) | Postgres auth mode: `entra` = AAD token via managed identity, no password. **Optional.** | App Service setting (backend) |
| `PRAXYS_PG_SERVER` | Postgres Flexible Server name. **Reserved / currently unused** - the on-demand backup jobs it gated were removed (Burstable tier can't do on-demand backups; PITR covers backup). Kept for a future off-site backup job. | (reserved) |

Application Insights resource names are tracked in
`.github/azure-observability.env`, not repository variables. The deploy
workflows use Azure OIDC to read each component's connection string at runtime;
the frontend workflow receives only the frontend/RUM value. The backend helper
also derives `PRAXYS_BACKEND_APPINSIGHTS_RESOURCE_ID` from the trusted component
and writes it directly to App Service; it is not a GitHub variable.

When one `main` push triggers both deployment surfaces, `deploy-backend.yml`
waits for every active frontend production run to settle, then verifies the
`deployed_sha` returned by the live `praxys-frontend` `/healthz` endpoint before
backend cutover. The frontend package contains
`frontend_server/_deployed_sha.txt`, generated from `GITHUB_SHA` during staging,
so the value comes from the code actually serving production rather than
workflow-list ordering. Rerunning a pre-marker historical workflow exposes no
SHA and therefore cannot masquerade as a compatible deployment.
Accepting a newer descendant handles GitHub's replacement of pending concurrency
runs when a frontend-only push follows closely. The required commit is the
latest frontend-triggering change in the backend SHA's first-parent history, so
a later backend-only push still waits for an earlier combined change. The new
frontend remains compatible with the Phase 1 API, so this frontend-first
ordering prevents an older bundle from hiding newly available alert and
platform aggregates during rollout.
Each workflow also serializes every production deployment, including `main`
pushes and release tags, without cancelling the active run. A newer run remains
queued and deploys last, so an older package cannot overwrite it.

Backend App Service setting, site-config, and telemetry-cutover writes recycle
the SCM container. `deploy-backend.yml` therefore waits at least 90 seconds and
requires three consecutive successful reads from the App Service deployment
endpoint before invoking ZipDeploy. Do not remove or shorten this settle gate:
deploying during the recycle is rejected with
`Deployment has been stopped due to SCM container restart`. Each probe has a
20-second command timeout and the full gate is capped at eight minutes so a
stalled SCM endpoint cannot monopolize the serialized production lane.

### Azure App Service → Application settings (backend `trainsight-app`)
Source of truth = `deploy-backend.yml`. Literals set inline: `DATA_DIR=/home/data`,
`WEBSITES_PORT=8000`, `SCM_DO_BUILD_DURING_DEPLOYMENT=true`,
`WEBSITE_HTTPLOGGING_RETENTION_DAYS=3`. `APPLICATIONINSIGHTS_CONNECTION_STRING`
and `PRAXYS_BACKEND_APPINSIGHTS_RESOURCE_ID` come from
`appi-praxys-backend` through `scripts/appinsights_boundary.sh`; everything else
comes from the secrets/variables above.

### Azure Key Vault (`kv-trainsight`)
- RSA key `trainsight-master-key` — the master key that wraps the per-user
  Fernet data-encryption keys (DEKs) protecting platform credentials
  (`db/crypto.py`). The App Service MI has *Key Vault Crypto User*. **Not** a
  plain env var.

### Local development → `.env`
Local only; never committed. See [`.env.example`](../../.env.example) for the full
annotated list. Minimum: `PRAXYS_LOCAL_ENCRYPTION_KEY` (Fernet); `PRAXYS_ENV=development`
to boot without a JWT secret.

### Application Insights trust boundary (#417)

Both components store data in `log-trainsight`, but they have separate ingestion
identities and resource IDs:

| Component | Purpose | Ingestion auth | Exposed to browser |
|---|---|---|---|
| `appi-trainsight` | SPA page views, dependencies, exceptions, Web Vitals; homepage availability test | Local/instrumentation-key auth enabled | **Yes** — expected |
| `appi-praxys-backend` | API requests/traces/logs, `praxys.*` product and Coach signals, backend alerts, API availability test | Entra-only (`DisableLocalAuth=true`) through `trainsight-app` MI | **No** |

The existing `appi-trainsight` instrumentation key was already shipped in
browser bundles, so it is permanently treated as untrusted RUM ingestion. The
new backend component was created with a fresh key and immediately locked to
Entra authentication. Sharing a Log Analytics workspace does not collapse the
boundary: alerts and queries remain scoped to the component resource ID (or
filter `_ResourceId` at workspace scope).

The workspace must keep
`features.enableLogAccessUsingOnlyResourcePermissions=true`. That setting lets
the backend query its linked component with exact-resource `Monitoring Reader`
instead of granting workspace-wide read access; `backend-preflight` rejects
drift.

The runtime identity is the App Service system-assigned identity unless the
`trainsight-app` setting `AZURE_CLIENT_ID` names an attached user-assigned
identity. `backend-preflight` resolves that effective identity and checks both
roles against it; changing `AZURE_CLIENT_ID` without attaching and granting the
matching identity blocks deployment.

#### One-time provisioning

```bash
RG=rg-trainsight
WORKSPACE_ID=$(az monitor log-analytics workspace show \
  -g "$RG" -n log-trainsight --query id -o tsv)
az resource update --ids "$WORKSPACE_ID" \
  --set properties.features.enableLogAccessUsingOnlyResourcePermissions=true

# Existing frontend component: keep local auth enabled for the browser SDK.
FRONTEND_ID=$(az resource show -g "$RG" -n appi-trainsight \
  --resource-type Microsoft.Insights/components --query id -o tsv)
az resource update --ids "$FRONTEND_ID" \
  --set properties.DisableLocalAuth=false \
        tags.trustBoundary=frontend \
        tags.managedBy=deploy-frontend-appservice

# Backend-only component. Safe to re-run if it already exists by skipping create.
az monitor app-insights component create \
  -g "$RG" -a appi-praxys-backend -l eastasia \
  --workspace "$WORKSPACE_ID" --kind web --application-type web
BACKEND_ID=$(az resource show -g "$RG" -n appi-praxys-backend \
  --resource-type Microsoft.Insights/components --query id -o tsv)
az resource update --ids "$BACKEND_ID" \
  --set properties.DisableLocalAuth=true \
        tags.trustBoundary=backend \
        tags.managedBy=deploy-backend

# The deploy identity is RG Contributor and cannot grant RBAC; an operator with
# role-assignment permission performs this once.
MI=$(az webapp identity show -g "$RG" -n trainsight-app \
  --query principalId -o tsv)
az role assignment create \
  --assignee-object-id "$MI" \
  --assignee-principal-type ServicePrincipal \
  --role "Monitoring Metrics Publisher" \
  --scope "$BACKEND_ID"
az role assignment create \
  --assignee-object-id "$MI" \
  --assignee-principal-type ServicePrincipal \
  --role "Monitoring Reader" \
  --scope "$BACKEND_ID"
```

For a user-assigned identity, first mirror every runtime grant held by the
system-assigned identity (including Key Vault and PostgreSQL access), attach it
to `trainsight-app`, set its client ID as the `AZURE_CLIENT_ID` App Service
setting, and use that identity's `principalId` as `MI` for both monitoring role
assignments above.

Record only the five non-secret identifiers in
`.github/azure-observability.env`. Do **not**
create `APPLICATIONINSIGHTS_CONNECTION_STRING` or
`VITE_APPINSIGHTS_CONNECTION_STRING` GitHub variables. On every deployment:

1. `backend-preflight` confirms distinct resources, shared workspace linkage,
   backend local-auth disabled, exact-resource `Monitoring Metrics Publisher`
   and `Monitoring Reader` RBAC for the effective runtime managed identity, and
   a 401/403 response when an anonymous forged `praxys.product_event` is sent
   with the backend instrumentation key.
2. The backend cutover updates the App Service routing plus all backend alert
   scopes as one rollback-guarded operation. Azure makes scheduled-query scopes
   immutable, so the helper preserves each full rule definition and recreates
   it under the same name with the new component scope. Deletion ignores only a
   confirmed 404; creation retries and then compares the complete normalized
   rule (criteria, actions, severity, cadence, identity, and tags). The same
   transaction writes `PRAXYS_BACKEND_APPINSIGHTS_RESOURCE_ID`, enabling the
   admin operations console only while the trusted backend boundary is active.
3. `frontend-resolve` refuses to build unless only the frontend component allows
   local auth, then injects that frontend connection string into Vite.

#### Verify production

```bash
set -a
source .github/azure-observability.env
set +a
export GITHUB_ENV=$(mktemp)
bash scripts/appinsights_boundary.sh backend-preflight

BACKEND_ID=$(az resource show -g "$AZURE_RESOURCE_GROUP" \
  -n "$BACKEND_APPINSIGHTS_NAME" \
  --resource-type Microsoft.Insights/components --query id -o tsv)
az resource show --ids "$BACKEND_ID" \
  --query "{workspace:properties.WorkspaceResourceId,localAuthDisabled:properties.DisableLocalAuth}" \
  -o table
az webapp config appsettings list -g "$AZURE_RESOURCE_GROUP" \
  -n trainsight-app \
  --query "[?name=='APPLICATIONINSIGHTS_CONNECTION_STRING' || name=='PRAXYS_BACKEND_APPINSIGHTS_RESOURCE_ID'].{name:name,value:value}" \
  -o table
MI=$(az webapp identity show -g "$AZURE_RESOURCE_GROUP" -n trainsight-app \
  --query principalId -o tsv)
az role assignment list --assignee-object-id "$MI" --scope "$BACKEND_ID" \
  --query "[?roleDefinitionName=='Monitoring Metrics Publisher' || roleDefinitionName=='Monitoring Reader'].{role:roleDefinitionName,scope:scope}" \
  -o table
```

The preflight's forged-event probe is the trust test: HTTP 401/403 proves that a
browser possessing an instrumentation key cannot place
`praxys.product_event` or `praxys.coach_feedback` into the backend component.
The authenticated product API can still accept its documented enum payload,
but the server owns the telemetry timestamp, pseudonym, provenance, and final
dimensions.

#### Rollback

`backend-cutover` captures the prior App Service value, scheduled-query scopes,
web-test link, and metric-alert component. Any failed mutation restores all of
them automatically. To reverse a successful cutover, pause/revert the backend
deploy workflow first (otherwise the next deploy re-applies the boundary), then
run the rollback mode:

```bash
set -a
source .github/azure-observability.env
set +a
bash scripts/appinsights_boundary.sh rollback-to-frontend
```

The reverse cutover atomically restores backend routing, all five scheduled
queries, the API web-test hidden link, and its metric-alert component to
`appi-trainsight`. It also removes
`PRAXYS_BACKEND_APPINSIGHTS_RESOURCE_ID`, so the in-app admin Azure sections
become explicitly unavailable rather than reading the untrusted browser
component. It restores the previous shared-resource behavior and therefore
removes the trust boundary; use it only as temporary telemetry recovery while
fixing the backend component or RBAC.

## Adding a NEW backend setting (checklist)

1. Read it in code via `os.environ` / `getenv_compat` (treat unset as a safe default).
2. Add it to `.env.example` (annotated) for local dev.
3. Add it to `deploy-backend.yml`: the `env:` block (from `secrets.*` or `vars.*`)
   **and** the `az webapp config appsettings set` arg list. Azure-derived routing
   values such as Application Insights belong in a deployment helper instead.
4. If it must be present, add it to the *required-settings* loop; if optional,
   **leave it out** of that loop so an unset value can't fail the deploy.
5. Create the GitHub secret (sensitive) or variable (non-sensitive).

> Example: the feedback → GitHub-issue settings (`PRAXYS_GITHUB_APP_*`,
> `PRAXYS_FEEDBACK_GITHUB_*`) follow exactly this pattern and are intentionally
> optional. (Added by the feedback feature — praxys-run/praxys#328.)

### Feedback screenshot storage (Azure Blob, keyless)

Screenshots attached to feedback (issue #337) are stored **privately** in Blob
(reusing the `stperftrainsight` account). Auth is keyless via the backend's
system-assigned managed identity — no key or connection string. One-time infra:

```bash
# 1. Dedicated container (kept separate from the perf data in this account)
az storage container create --account-name stperftrainsight \
  --name feedback-screenshots --auth-mode login

# 2. Grant the app MI data access on JUST that container (least privilege)
MI=$(az webapp identity show -n trainsight-app -g rg-trainsight --query principalId -o tsv)
SUB=$(az account show --query id -o tsv)
az role assignment create --assignee-object-id "$MI" --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" \
  --scope "/subscriptions/$SUB/resourceGroups/rg-trainsight/providers/Microsoft.Storage/storageAccounts/stperftrainsight/blobServices/default/containers/feedback-screenshots"

# 3. Register the two non-secret GitHub Actions variables (the source of truth).
#    deploy-backend.yml syncs them to the App Service settings on the next deploy.
gh variable set PRAXYS_FEEDBACK_BLOB_ACCOUNT_URL --body "https://stperftrainsight.blob.core.windows.net"
gh variable set PRAXYS_FEEDBACK_BLOB_CONTAINER   --body "feedback-screenshots"
```

The two `PRAXYS_FEEDBACK_BLOB_*` variables above point the app at it. Unset them
and the app falls back to local filesystem storage under `DATA_DIR` (persistent
on `/home`, but not the recommended long-term home). `api/feedback_storage.py`
selects the backend and authenticates with `DefaultAzureCredential`.

### The change loop — coding-agent labels & assignment (issue #362)

`agent-ready` (auto-added to qualifying, actionable bugs by `api/feedback_triage.py`, or added
by hand) triggers `.github/workflows/assign-copilot.yml`, which assigns the issue
to the Copilot coding agent. These are **repo settings, not deploy-managed**:

- **Labels** `agent-ready` and `backlog` (optionally `later`) are created once
  with `gh label create` — see [change-loop.md](./change-loop.md).
- **Required secret for auto-assign** `COPILOT_ASSIGN_TOKEN` (fine-grained PAT,
  *Issues: write*, this repo only, with expiry). Agent assignment needs a user
  token — the built-in `GITHUB_TOKEN` is forbidden (issue #400); without it the
  workflow fails loudly and a human assigns manually. See
  [change-loop.md](./change-loop.md) §3.
- **Optional flag** `PRAXYS_AGENT_READY_SHADOW=true` (App Service setting)
  computes the agent-ready decision but withholds the label — measure precision
  before going live (issue #377).
- **Agent environment:** `.github/workflows/copilot-setup-steps.yml` preinstalls
  the toolchain so the agent can run `pytest` / `npm` deterministically.
- The **workflow file is the source of truth** for the trigger + assignment
  logic; branch protection on `main` keeps merge human.

### Azure Database for PostgreSQL (#360)

The backend is dual-backend: `PRAXYS_DATABASE_URL` empty/unset = SQLite on
`/home/data`; set it to a Postgres DSN and the app uses Postgres. Keep it empty
until the cutover so this can ship ahead of the migration. Full runbook:
[postgres-migration.md](./postgres-migration.md).

- `PRAXYS_DATABASE_URL` (**secret**) - the Postgres DSN. With Entra/MI auth it
  carries no password.
- `PRAXYS_DB_AUTH` (**variable**) - `entra` makes the app authenticate with an
  AAD token from its managed identity (no DB password anywhere).
- `PRAXYS_PG_SERVER` (**variable**) - the Flexible Server name. Reserved /
  currently unused (the on-demand backup jobs it gated were removed - Burstable
  can't do on-demand backups; PITR covers backup). Kept for future off-site
  backup automation.

```bash
gh variable set PRAXYS_PG_SERVER --body "praxys-pg"
gh variable set PRAXYS_DB_AUTH   --body "entra"
gh secret   set PRAXYS_DATABASE_URL --body "postgresql://trainsight-app@praxys-pg.postgres.database.azure.com:5432/praxys?sslmode=require"
```

**Status (2026-07-04):** all three are **set** and production runs on Postgres.
`PRAXYS_DATABASE_URL` = `postgresql://trainsight-app@praxys-pg.postgres.database.azure.com:5432/praxys?sslmode=require`
(no password — Entra/MI). They remain out of the required-settings loop, so
clearing `PRAXYS_DATABASE_URL` cleanly rolls back to the frozen SQLite file.
Provisioning + PITR + MI-as-AAD-principal wiring: [postgres-migration.md](./postgres-migration.md).

### Database connection budget, pool sizing & Always On

The production DB is a **Burstable B1ms** Flexible Server: `max_connections=50`
(Azure default for the tier), of which ~15 are reserved
(`superuser_reserved_connections=10` + `reserved_connections=5`, both Azure
defaults) — leaving **~35 usable by the app**. Don't lower the reserved values;
they're Azure-managed.

The backend's SQLAlchemy pools are bounded (`db/session.py`) and tunable via
optional App Service settings (defaults shown):

| Setting | Default | Meaning |
|---|---|---|
| `PRAXYS_DB_POOL_SIZE` | `5` | Steady pool size, **per engine, per worker** |
| `PRAXYS_DB_MAX_OVERFLOW` | `5` | Burst connections above `pool_size` |
| `PRAXYS_DB_POOL_RECYCLE` | `1800` | Recycle (reconnect) a connection after N seconds |

There are **two** engines (sync + async), so one gunicorn worker holds at most
`2 × (pool_size + max_overflow)` = **20** connections — under the 35-slot
budget. If you raise the worker count or pool sizes, keep
`workers × 2 × (pool_size + max_overflow)` **< 35**, or move off Burstable.
These envs are optional (not in the required-settings loop).

**Always On = `true`** — App Service **site config** (NOT an app setting), so a
separate command, owned by `deploy-backend.yml`:
`az webapp config set --name trainsight-app --resource-group rg-trainsight --always-on true`.
It keeps one warm container instead of stop/starting on idle; each recycle
abandons the container's pool as idle "zombie" backends that linger until
TCP-keepalive reap (~6 min), and that churn helped exhaust Postgres in the
2026-07-05 outage. The app also disposes its engines on shutdown
(`dispose_engines`, `api/main.py` lifespan) so a *clean* recycle frees
connections immediately.

Guarded by two alerts (see
[monitoring-and-alerts.md](./monitoring-and-alerts.md)):
`praxys-pg-connections-high` (Sev 2, `active_connections` > 40) and
`praxys-db-health-unhealthy` (Sev 1, DB unreachable/corrupt).

### Self-registration gate + email

Opening self-registration is **runtime config, not a setting**: an admin toggles
it and sets the seat cap on the Admin page (persisted in the `app_config` DB table
via `api/app_config.py`). Nothing to deploy for that — see
[admin-tasks.md](./admin-tasks.md).

The *email* prerequisites ARE optional settings (tables above): the `PRAXYS_SMTP_*`
group + `PRAXYS_APP_BASE_URL`. They power (a) double-opt-in email verification for
code-less sign-ups and (b) emailing invitation codes to waitlist signups. Unset →
the app still works: codes are shown for the admin to copy/mailto by hand, and open
sign-ups are created verified (no ownership check possible). To provision (WeCom /
Tencent Exmail):

```bash
# 1. In the Exmail mailbox: 设置 → 账号 → enable POP3/IMAP/SMTP, then generate a
#    客户端授权码 (client authorization code) — that is PRAXYS_SMTP_PASSWORD.
# 2. Register the non-secret variables + the secret (source of truth):
gh variable set PRAXYS_SMTP_HOST     --body "smtp.exmail.qq.com"
gh variable set PRAXYS_SMTP_PORT     --body "465"
gh variable set PRAXYS_SMTP_USER     --body "no-reply@praxys.run"
gh variable set PRAXYS_SMTP_FROM     --body "Praxys <no-reply@praxys.run>"
gh variable set PRAXYS_APP_BASE_URL  --body "https://praxys.run"
gh secret   set PRAXYS_SMTP_PASSWORD --body "<客户端授权码>"
# 3. Re-deploy the backend — deploy-backend.yml syncs them to App Service.
```

Azure App Service blocks outbound port **25** but allows **465/587** to an
authenticated relay like Exmail. The `EmailSender` interface (`api/email_sender.py`)
is provider-agnostic, so Azure Communication Services (HTTPS) can be swapped in
later without touching call sites if SMTP is ever blocked or Exmail's daily cap is
outgrown.

## Rotation

| Value | How | Impact |
|---|---|---|
| `PRAXYS_JWT_SECRET` | New `secrets.PRAXYS_JWT_SECRET`, re-deploy backend | **All active sessions invalidated** — every user must log in again. |
| `WECHAT_MINIAPP_SECRET` | Rotate in mp.weixin.qq.com, update GitHub secret, re-deploy | Mini program auth briefly fails until deploy lands. |
| `WECHAT_MINIAPP_UPLOAD_KEY` | Regenerate in mp.weixin.qq.com, update GitHub secret | Only affects mini program CI publishing. |
| Frontend/backend Application Insights routing | Provision the replacement component, update `.github/azure-observability.env`, grant backend MI RBAC if needed, and re-deploy | The workflows fetch fresh routing strings directly from Azure; no GitHub value rotates. |
| Feedback GitHub App key (`PRAXYS_GITHUB_APP_PRIVATE_KEY`) | Generate a new private key on the app, update the secret, re-deploy (rarely needed). Setup: [setup-github-app.md](./setup-github-app.md). | Issue auto-filing dormant until updated; rest of app unaffected. |
| SMTP auth code (`PRAXYS_SMTP_PASSWORD`) | Regenerate the 客户端授权码 in the Exmail/WeCom mailbox settings, update the GitHub secret, re-deploy. | Verification + invitation emails fail to send until updated (codes can still be copied by hand). |
| Key Vault RSA key `trainsight-master-key` | ⚠️ **High-impact** — the per-user DEKs were wrapped with the current key; rotating without a re-wrap/re-encrypt migration makes stored platform credentials undecryptable. **TODO(@dddtc2005):** document the re-wrap drill before rotating. | Users would have to reconnect platforms. |

## Related

- [deploy.md](./deploy.md) · [environment.md](./environment.md) · `docs/deployment.md`
- `.github/workflows/deploy-backend.yml` and `scripts/appinsights_boundary.sh`
  (source of truth for App Service settings and telemetry routing)

---
_Last reviewed: 2026-07-18 · Owner: @dddtc2005_
