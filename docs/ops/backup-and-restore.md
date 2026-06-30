# Backup & restore the database

> **Summary:** Take a consistent backup of the SQLite database and restore it.
> **Use when:** Before a risky migration/deploy, on a schedule, or to recover
> from data loss / corruption.

## What & where

The whole app state is one SQLite file: **`trainsight.db`** at
`DATA_DIR=/home/data` on the backend App Service `trainsight-app`. `/home` is
Azure App Service **persistent** storage (survives restarts/redeploys). There is
no separate managed DB — back up this file.

## Prerequisites

- `az` CLI logged in (Contributor on `rg-trainsight`).
- App Service SCM (Kudu) access — publishing creds:
  `az webapp deployment list-publishing-credentials -n trainsight-app -g rg-trainsight`.

## Steps — backup

A hot file copy can tear (SQLite WAL). Take a **consistent snapshot** with
`.backup`, then retrieve it.

```bash
# 1. SSH into the running container
az webapp ssh -n trainsight-app -g rg-trainsight
#    inside the container:
cd /home/data
sqlite3 trainsight.db ".backup '/home/data/backup-$(date -u +%Y%m%dT%H%M%SZ).db'"
exit

# 2. Download the snapshot via the Kudu VFS API (basic auth = publishing creds)
#    List: https://trainsight-app.scm.azurewebsites.net/api/vfs/data/
curl -u '<scm-user>:<scm-pass>' \
  "https://trainsight-app.scm.azurewebsites.net/api/vfs/data/backup-<ts>.db" \
  -o backup-<ts>.db
```

Store the snapshot off-box (e.g. the `perfbaselines-archive` blob on
`stperftrainsight`, or your own secure storage). Keep at least the last N daily
snapshots.

## Steps — restore

```bash
# 1. Stop the app so nothing writes mid-restore
az webapp stop -n trainsight-app -g rg-trainsight

# 2. Upload the snapshot over the live file via Kudu VFS (PUT). Also remove any
#    stale WAL sidecars so the restored .db isn't reconciled against old WAL.
curl -u '<scm-user>:<scm-pass>' -X PUT --data-binary @backup-<ts>.db \
  "https://trainsight-app.scm.azurewebsites.net/api/vfs/data/trainsight.db?recursive=false" \
  -H "If-Match: *"
# (delete trainsight.db-wal / -shm via the same VFS API if present)

# 3. Start; init_db() runs its additive migrations on boot
az webapp start -n trainsight-app -g rg-trainsight
```

## Verify

`curl -s https://api.praxys.run/api/health` → `ok`; log in and confirm recent
data is present. Check `az webapp log tail` for migration errors on boot.

## Rollback / Recovery

Keep the pre-restore file (download it before overwriting) so a bad restore is
itself reversible. If the app won't boot, restore the previous-known-good
snapshot.

## Related

- [disaster-recovery.md](./disaster-recovery.md) · [deploy.md](./deploy.md) · `db/session.py` (`init_db`)

---
_Last reviewed: 2026-06-30 · Owner: @dddtc2005 · TODO(@dddtc2005): pick a backup cadence + retention and (optionally) automate it._
