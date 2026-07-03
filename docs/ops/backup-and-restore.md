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

## Recover from corruption (no snapshot)

If `az webapp log tail` shows `sqlite3.DatabaseError: database disk image is
malformed` and you have **no backup**, salvage the live file with SQLite's
`.recover` (it parses the b-tree pages directly and rebuilds a clean DB,
skipping unreadable pages). Run inside `az webapp ssh` (or the Kudu console):

```bash
cd /home/data
ts=$(date -u +%Y%m%dT%H%M%SZ)
# 1. Preserve the corrupt triplet (reversible if recovery goes wrong)
cp -v trainsight.db "trainsight.db.corrupt.$ts"
[ -f trainsight.db-wal ] && cp -v trainsight.db-wal "trainsight.db-wal.corrupt.$ts"
[ -f trainsight.db-shm ] && cp -v trainsight.db-shm "trainsight.db-shm.corrupt.$ts"

# 2. Salvage into a fresh file (non-destructive)
sqlite3 trainsight.db ".recover" 2>recover.err | sqlite3 trainsight.rebuilt.db
sqlite3 trainsight.rebuilt.db "PRAGMA integrity_check;"   # want: ok
sqlite3 trainsight.rebuilt.db "SELECT count(*) FROM activities;"  # sanity

# 3. Stop the app so nothing writes, then swap in the rebuilt file
az webapp stop -n trainsight-app -g rg-trainsight    # from your workstation
mv trainsight.db "trainsight.db.corrupt.main.$ts"
rm -f trainsight.db-wal trainsight.db-shm            # stale sidecars
mv trainsight.rebuilt.db trainsight.db
az webapp start -n trainsight-app -g rg-trainsight   # init_db() re-adds any missing columns
```

If the container lacks the `sqlite3` CLI, run the same `.recover` from the app
venv's Python, or `apt-get install -y sqlite3` (you're root in the SSH shell).

## Prevent corruption

`trainsight.db` sits on Azure Files (SMB). Two rules keep it safe (both enforced
in code / docs as of the WAL-corruption incident):

1. **No WAL on `/home`.** SQLite WAL needs a shared-memory index (`-shm`) that
   does not work over a network filesystem — it corrupts the file. `db/session.py`
   pins `journal_mode=DELETE` + `synchronous=FULL` for exactly this reason; do
   not switch back to WAL while the DB is on Azure Files.
2. **One writer.** Run the backend with a **single** gunicorn worker so there is
   only one process writing the SQLite file — multiple worker processes over SMB
   is the other half of the corruption trigger. Set the startup command to e.g.
   `gunicorn -k uvicorn.workers.UvicornWorker -w 1 -b 0.0.0.0:8000 api.main:app`
   (`az webapp config set --startup-file "…"`). Scale out via App Service
   instances only if you first move off SQLite (managed DB) or a WAL-safe store.

**Take a snapshot before every risky deploy** (this incident had no backup):
`sqlite3 trainsight.db ".backup '/home/data/backups/pre-deploy-<ts>.db'"`.

## Related

- [disaster-recovery.md](./disaster-recovery.md) · [deploy.md](./deploy.md) · `db/session.py` (`init_db`, `_SQLITE_PRAGMAS`)

---
_Last reviewed: 2026-06-30 · Owner: @dddtc2005 · TODO(@dddtc2005): pick a backup cadence + retention and (optionally) automate it._
