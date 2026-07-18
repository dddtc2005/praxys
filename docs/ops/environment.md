# Environment reference

> **Summary:** The canonical Azure resources, names, IDs, and hostnames for the
> production Praxys deployment.
> **Use when:** A runbook or command needs a resource name / subscription / RG,
> or you're onboarding to the Azure environment.

> Note: many resources still carry the legacy `trainsight` name — the on-disk
> SQLite file and several resource names predate the Praxys rename and were
> kept to avoid data-migration risk. This is expected.

## Azure

| Thing | Value | Source |
|---|---|---|
| Subscription ID | `3ff02750-211c-4579-94a6-8c9af4e6d891` | `docs/perf-baselines/ci-setup.md` |
| Resource group | `rg-trainsight` | `.github/workflows/deploy-backend.yml` |
| Backend App Service | `trainsight-app` | `deploy-backend.yml` (`--name trainsight-app`) |
| Frontend App Service | `praxys-frontend` | `deploy-frontend-appservice.yml` |
| App Service plan | `plan-trainsight` (Linux B1, East Asia) | `docs/deployment.md`, `frontend_server` notes |
| PostgreSQL (**primary DB**, live 2026-07-04) | `praxys-pg` Flexible Server (Burstable B1ms, PG16, DB `praxys`, Entra auth, PITR 14d) | [postgres-migration.md](./postgres-migration.md); `PRAXYS_PG_SERVER` var |
| Key Vault | `kv-trainsight` (`https://kv-trainsight.vault.azure.net`) | live `KEY_VAULT_URL` |
| — RSA key | `trainsight-master-key` | live `KEY_VAULT_KEY_NAME` |
| Frontend Application Insights | `appi-trainsight` (Application ID `d10e388f-3a26-4c3d-b57d-d83fc4637a9b`; browser/RUM, local auth enabled) | `.github/azure-observability.env` |
| Backend Application Insights | `appi-praxys-backend` (Application ID `066f94a3-a340-498d-9ee1-6f093a7b8911`; managed-identity ingestion, local auth disabled) | `.github/azure-observability.env`, `scripts/appinsights_boundary.sh` |
| Log Analytics workspace | `log-trainsight` (shared storage; queries must retain component scope / `_ResourceId`) | `.github/azure-observability.env` |
| Perf-baseline storage | `stperftrainsight` (RG `rg-trainsight`, East Asia) | `docs/perf-baselines/ci-setup.md` |
| CI/deploy app registration | `trainsight-cicd` — appId `d3deb736-e95d-400e-b5a5-c2f76b23ae25` (OIDC federated creds `github-deploy`, `i18n`) | live `az ad app` |

## Hostnames

| Surface | URL |
|---|---|
| API | `https://api.praxys.run` |
| Web app | `https://www.praxys.run` |

## Identity & auth model

- **App → Key Vault / backend App Insights:** the backend App Service uses its
  **system-assigned managed identity** (no secret in app settings). The MI holds
  *Key Vault Crypto User* (key wrap/unwrap) and *Monitoring Metrics Publisher*
  on `appi-praxys-backend`. That component disables local authentication; the
  public browser connection string points only to `appi-trainsight`.
  See `api/main.py`, `.github/azure-observability.env`, and
  `scripts/appinsights_boundary.sh`.
- **GitHub Actions → Azure:** OIDC federated credentials on `trainsight-cicd`
  (tenant `bd18218b-ffc1-4eef-b717-fb07368336c0`, application
  `d3deb736-e95d-400e-b5a5-c2f76b23ae25`; subjects
  `repo:praxys-run/praxys:ref:refs/heads/main` and `…:i18n-azure-openai`).
  No client secret. The identity also has *Cognitive Services OpenAI User* on the
  Foundry resource. Agentic Workflows reuse the `main` subject for keyless
  `gpt-5.4` inference: PR validation completes first, then `workflow_run` starts
  the agent from the default branch. Moving repos to the `praxys-run` org
  changes these subjects — see [org-migration.md](./org-migration.md). See
  [config-and-secrets.md](./config-and-secrets.md).

## Data

- **Primary store:** **Azure Database for PostgreSQL** `praxys-pg` (live since
  2026-07-04; `PRAXYS_DATABASE_URL` set, keyless Entra/MI auth), schema via
  Alembic (`alembic upgrade head` on boot, advisory-locked). The code is
  dual-backend: with `PRAXYS_DATABASE_URL` unset it falls back to SQLite
  `trainsight.db` at `DATA_DIR=/home/data` (schema via `create_all`) — used for
  local dev / tests and as the frozen rollback artifact. See
  [postgres-migration.md](./postgres-migration.md).
- **Platform credentials:** Fernet-encrypted in the DB; each user's Fernet DEK is
  wrapped by the Key Vault RSA master key (`db/crypto.py`).

## Repo governance

- **Owner:** the repos live in the **`praxys-run`** org (GitHub **Free**; public repos keep branch protection + unlimited Actions minutes). Migrated from the `dddtc2005` personal account on 2026-07-10 — see [org-migration.md](./org-migration.md).
- **`main` protection is two layers.** (1) **Classic branch protection**: required status check `backend-tests` (`ci-backend.yml`, #361) blocks merge on a failing `pytest`, **admins included** (`enforce_admins`); managed via `repos/praxys-run/praxys/branches/main/protection`. (2) **Repo ruleset `default`** (id `15208143`): **squash-only** merges + **1 required review**, with a **repo-admin `Always` bypass** so the solo maintainer self-merges a green PR; managed via the rulesets API. ⚠️ **Transfer gotcha:** moving a repo between accounts **wipes the ruleset's `bypass_actors`** — after the org migration the bypass list was empty (deadlocking solo self-merge) and had to be restored (`PUT repos/praxys-run/praxys/rulesets/15208143`, requires `admin:org` scope + the full ruleset body).

## Related

- [config-and-secrets.md](./config-and-secrets.md) · [deploy.md](./deploy.md)
- `docs/deployment.md` (one-time Azure setup) · `docs/perf-baselines/azure-provisioning.md`

---
_Last reviewed: 2026-07-18 · Owner: @dddtc2005_
