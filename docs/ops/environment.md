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

- **Primary store:** SQLite `trainsight.db` on the backend App Service at
  `DATA_DIR=/home/data` (persistent). Schema auto-migrates on boot via
  `db/session.py::init_db()`.
- **Platform credentials:** Fernet-encrypted in the DB; each user's Fernet DEK is
  wrapped by the Key Vault RSA master key (`db/crypto.py`).

## Related

- [config-and-secrets.md](./config-and-secrets.md) · [deploy.md](./deploy.md)
- `docs/deployment.md` (one-time Azure setup) · `docs/perf-baselines/azure-provisioning.md`

---
_Last reviewed: 2026-06-30 · Owner: @dddtc2005_
