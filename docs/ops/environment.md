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
| Application Insights | connection string in app settings; MI-authenticated | `.env.example`, `api/main.py` |
| Perf-baseline storage | `stperftrainsight` (RG `rg-trainsight`, East Asia) | `docs/perf-baselines/ci-setup.md` |
| CI app registration | `trainsight-ci` (OIDC federated cred) | `docs/deployment.md` |

## Hostnames

| Surface | URL |
|---|---|
| API | `https://api.praxys.run` |
| Web app | `https://www.praxys.run` |

## Identity & auth model

- **App → Key Vault / App Insights:** the backend App Service uses its
  **system-assigned managed identity** (no secret in app settings). The MI holds
  *Key Vault Crypto User* (key wrap/unwrap) and *Monitoring Metrics Publisher*.
  See `api/main.py` (managed-identity wiring) and `.env.example`.
- **GitHub Actions → Azure:** OIDC federated credential on `trainsight-ci`,
  subject `repo:dddtc2005/praxys:ref:refs/heads/main`. No client secret. See
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

- **`main` branch protection.** A required status check `backend-tests` (from `.github/workflows/ci-backend.yml`, issue #361) gates every PR to `main`: a failing backend `pytest` run blocks merge, **admins included** (`enforce_admins`). No required human review (`required_pull_request_reviews` unset) so the solo maintainer can self-merge a green PR. Managed via the branch-protection API on `repos/dddtc2005/praxys/branches/main/protection` — update that rule to change the required checks.

## Related

- [config-and-secrets.md](./config-and-secrets.md) · [deploy.md](./deploy.md)
- `docs/deployment.md` (one-time Azure setup) · `docs/perf-baselines/azure-provisioning.md`

---
_Last reviewed: 2026-07-05 · Owner: @dddtc2005_
