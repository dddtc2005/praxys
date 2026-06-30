# Disaster recovery — rebuild from scratch

> **Summary:** Recreate the whole Praxys deployment in a fresh resource group /
> subscription and restore data.
> **Use when:** The resource group is lost, a region is unavailable, or you're
> standing up a parallel environment.

This runbook is a checklist that chains the others — it doesn't duplicate them.

## Recovery objectives

- **RPO** (max acceptable data loss) = your backup cadence. **TODO(@dddtc2005):
  decide** (e.g. daily snapshots → up to 24h loss).
- **RTO** (max acceptable downtime) = provisioning + restore time. **TODO:
  decide** and time a drill.

## Steps

1. **Provision infra.** Follow `docs/deployment.md` → *Azure Setup (One-Time)*:
   resource group, App Service plan + the two sites (`trainsight-app`,
   `praxys-frontend`), Key Vault `kv-trainsight`, App Insights, managed identity
   + RBAC. Resource names + IDs: [environment.md](./environment.md).
2. **Re-create the master key.** Key Vault RSA key `trainsight-master-key`. ⚠️ If
   this is a *new* key (old vault unrecoverable), previously-encrypted platform
   credentials can't be decrypted — users must reconnect platforms. Restoring the
   *same* vault/key preserves them.
3. **Wire CI + config.** GitHub OIDC federated credential + Actions
   secrets/variables ([config-and-secrets.md](./config-and-secrets.md)).
4. **Deploy.** Push `main` (or run `deploy-backend.yml` / `deploy-frontend-appservice.yml`).
5. **Restore data.** Put the latest `trainsight.db` snapshot in place
   ([backup-and-restore.md](./backup-and-restore.md)).
6. **Re-point DNS.** `api.praxys.run` / `www.praxys.run` to the new sites; re-issue
   managed certs (`docs/deployment.md` → custom domains).

## Verify

Health endpoints green; a known user can log in and see their historical data;
a sync succeeds.

## Related

- `docs/deployment.md` (the authoritative build steps) · [backup-and-restore.md](./backup-and-restore.md)
  · [config-and-secrets.md](./config-and-secrets.md) · [secret-rotation.md](./secret-rotation.md)

---
_Last reviewed: 2026-06-30 · Owner: @dddtc2005 · TODO(@dddtc2005): run a restore drill and record real RPO/RTO._
