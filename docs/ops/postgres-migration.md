# Migrate the database from SQLite to Azure Postgres (#360)

> **Summary:** Provision Azure Database for PostgreSQL (Flexible Server),
> move the production data off the SQLite file, and cut over the app with a
> rollback path.
> **Use when:** Performing the #360 migration, or standing up Postgres in a
> fresh environment.

The app is **dual-backend**: with `PRAXYS_DATABASE_URL` unset it uses the
legacy SQLite file at `/home/data/trainsight.db`; set it to a Postgres DSN and
the app uses Postgres (schema managed by Alembic, applied on boot under an
advisory lock). This lets you deploy the Postgres-capable code first and flip
the switch later.

## Already provisioned (2026-07-04)

The Flexible Server is live, so a cutover can skip steps 1-3 below:

| Thing | Value |
|---|---|
| Server | `praxys-pg` (Burstable `Standard_B1ms`, PG 16, eastasia) |
| FQDN | `praxys-pg.postgres.database.azure.com` |
| Database | `praxys` |
| Backups | PITR, 14-day retention (geo-redundant: off) |
| Auth | Entra **and** password enabled; app MI `trainsight-app` is an Entra admin |
| Admin (migration only) | user `praxysadmin`; password in Key Vault `kv-trainsight` secret `praxys-pg-admin-password` |
| Firewall | `AllowAzureServices` (App Service reachability) |
| Schema | Alembic baseline already applied (`alembic check` clean) |
| GitHub config | variables `PRAXYS_PG_SERVER=praxys-pg`, `PRAXYS_DB_AUTH=entra` set |

Remaining operator steps: **merge + deploy this PR** (SQLite still active), then
**step 4 (dry-run)** and **step 5 (cutover)**, then **step 6**. The app connects
keyless (Entra/MI, username `trainsight-app`); the `praxysadmin` password is only
for the one-time data load - rotate it or disable password-auth afterward.

## Prerequisites

- `az` CLI logged into the Praxys subscription (Contributor on `rg-trainsight`).
- The Postgres-capable backend already deployed (this PR merged + deployed;
  SQLite still active because `PRAXYS_DATABASE_URL` is unset).
- A short **maintenance window** for the final cutover.
- Local: the repo + venv (to run `scripts/migrate_sqlite_to_postgres.py`).

## Steps

### 1. Provision the Flexible Server (Burstable to start)

```bash
az postgres flexible-server create \
  --resource-group rg-trainsight \
  --name praxys-pg \
  --location eastasia \
  --tier Burstable --sku-name Standard_B1ms \
  --storage-size 32 \
  --version 16 \
  --database-name praxys \
  --backup-retention 14 \
  --microsoft-entra-auth Enabled \
  --password-auth Disabled \
  --public-access None
```

`--backup-retention 14` turns on managed automated backups + point-in-time
restore (PITR) with a 14-day window (this is the automated backup that #349
asked for; range 7-35). `--microsoft-entra-auth Enabled --password-auth
Disabled` = keyless auth only (no DB password anywhere). Adjust
`--public-access` to a firewall rule / private endpoint per your network model
(`None` = no public access; add a rule or VNet integration so the App Service
can reach it).

### 2. Make the App Service managed identity a Postgres AAD principal

The backend authenticates with an AAD token from its system-assigned managed
identity. Register that identity on the server; the DSN username is its name.

```bash
APP_MI=$(az webapp identity show -n trainsight-app -g rg-trainsight --query principalId -o tsv)
az postgres flexible-server microsoft-entra-admin create \
  --resource-group rg-trainsight --server-name praxys-pg \
  --display-name trainsight-app --object-id "$APP_MI" --type ServicePrincipal
```

> Making the MI an Entra **admin** is the simplest path and is fine for the
> single-app deployment. For least privilege you can instead connect as the
> admin once and `CREATE ROLE "trainsight-app" WITH LOGIN` + grant only the
> needed table privileges. Track as a hardening follow-up.
> **Verify:** confirm the username the MI connects as matches the
> `--display-name` above before relying on it in the DSN.

### 3. Register the GitHub config (do NOT flip yet)

`deploy-backend.yml` syncs these to App Service on the next deploy. Setting an
empty/absent `PRAXYS_DATABASE_URL` keeps SQLite, so registering the server var
first (for the backup jobs) is safe.

```bash
# Backup jobs (pre-deploy step + db-backup.yml) key off this:
gh variable set PRAXYS_PG_SERVER --body "praxys-pg"
# Keyless auth mode:
gh variable set PRAXYS_DB_AUTH   --body "entra"
```

### 4. Dry-run the migration into a scratch database

Prove the data + encrypted-credential blobs move cleanly before touching the
live cutover. Take a consistent SQLite snapshot (see
[backup-and-restore.md](./backup-and-restore.md)), download it, then:

```bash
# scratch DB on the server so the dry run does not touch the real target
az postgres flexible-server db create -g rg-trainsight -s praxys-pg -d praxys_dryrun

# fetch the migration admin password (Key Vault) and run with the same
# encryption context as prod (Key Vault access to the Fernet master key):
PGPW=$(az keyvault secret show --vault-name kv-trainsight --name praxys-pg-admin-password --query value -o tsv)
.venv/bin/python -m scripts.migrate_sqlite_to_postgres \
  --sqlite ./trainsight-snapshot.db \
  --postgres "postgresql://praxysadmin:${PGPW}@praxys-pg.postgres.database.azure.com:5432/praxys_dryrun?sslmode=require" \
  --wipe --verify-decrypt
```

The script creates the schema via Alembic, copies every table (parent-first),
resets SERIAL sequences, and asserts row-count parity + that credential blobs
still decrypt. Fix any error before proceeding. Drop the scratch DB when done.

### 5. Cutover (maintenance window)

```bash
# a. Stop writes: stop the app (or set the registration gate closed + announce)
az webapp stop -n trainsight-app -g rg-trainsight

# b. Final consistent SQLite snapshot (the rollback artifact) + download it.
#    (See backup-and-restore.md -> "Steps - backup".)

# c. Load prod data into the real target DB (praxysadmin password from Key Vault)
PGPW=$(az keyvault secret show --vault-name kv-trainsight --name praxys-pg-admin-password --query value -o tsv)
.venv/bin/python -m scripts.migrate_sqlite_to_postgres \
  --sqlite ./trainsight-final.db \
  --postgres "postgresql://praxysadmin:${PGPW}@praxys-pg.postgres.database.azure.com:5432/praxys?sslmode=require" \
  --wipe --verify-decrypt

# d. Flip the app to Postgres: store the DSN secret, then re-deploy so
#    deploy-backend.yml syncs it to the App Service settings.
gh secret set PRAXYS_DATABASE_URL \
  --body "postgresql://trainsight-app@praxys-pg.postgres.database.azure.com:5432/praxys?sslmode=require"
#    Trigger a backend deploy (push to main, or re-run deploy-backend.yml).

# e. Start the app (deploy will start it; otherwise:)
az webapp start -n trainsight-app -g rg-trainsight
```

On boot the app runs `alembic upgrade head` (advisory-locked) against Postgres
and the startup integrity check (`SELECT 1`).

### 6. Point the App Service health check at the readiness probe

Set the health-check path to `/api/health/ready` (DB-backed, issue #350) so a
corrupt/unreachable DB shows unhealthy instead of the liveness-only
`/api/health` masking it. Azure Portal: App Service -> Monitoring -> Health
check -> path `/api/health/ready`.

## Verify

- `curl -s https://api.praxys.run/api/health/ready` -> `{"status":"ready","database":"ok"}`.
- Log in; recent activities / recovery / plan are present.
- Trigger a sync; it succeeds and new rows appear.
- `az postgres flexible-server backup list -g rg-trainsight -n praxys-pg` shows
  the pre-deploy on-demand backup plus managed backups.
- App logs show `Alembic migrations up to date` and `Database startup check OK (postgresql)`.

## Rollback / Recovery

The legacy SQLite file on `/home/data` is untouched by the cutover, so rollback
is fast:

```bash
gh secret set PRAXYS_DATABASE_URL --body ""   # empty = fall back to SQLite
# re-deploy the backend; on boot the app uses /home/data/trainsight.db again
```

Writes made to Postgres during the window are lost on rollback (acceptable
inside a maintenance window). For a data problem discovered later, restore
Postgres via PITR (see [backup-and-restore.md](./backup-and-restore.md)).

## Related

- `scripts/migrate_sqlite_to_postgres.py` (the data-copy tool) ·
  `tests/test_pg_migration.py` (round-trip test)
- `db/session.py` (dual-backend engine, Alembic-on-boot, startup check) ·
  `alembic/` (schema)
- [backup-and-restore.md](./backup-and-restore.md) · [config-and-secrets.md](./config-and-secrets.md)
  · [environment.md](./environment.md) · [disaster-recovery.md](./disaster-recovery.md)

---
_Last reviewed: 2026-07-04 · Owner: @dddtc2005 · TODO(@dddtc2005): run the dry-run drill and record real cutover timing; consider a least-privilege (non-admin) DB role for the app MI._