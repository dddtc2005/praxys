# Incident response — service degraded or down

> **Summary:** First-response triage for "the app is down / erroring".
> **Use when:** Health checks fail, users report outages, or alerts fire.

## Quick triage

```bash
curl -s https://api.praxys.run/api/health      # expect {"status":"ok"}
curl -s https://api.praxys.run/api/version     # which build is live?
curl -s -o /dev/null -w "%{http_code}\n" https://www.praxys.run/healthz   # expect 200
```

| Symptom | Likely area | Go to |
|---|---|---|
| `/api/health` fails / 5xx | backend down or crashing | **Backend** below |
| `/healthz` fails, API ok | frontend host | **Frontend** below |
| Both ok, data stale for some users | sync stuck | [sync-troubleshooting.md](./sync-troubleshooting.md) |
| Started right after a deploy | bad release | [deploy.md](./deploy.md) → Rollback |
| `/api/health` ok **but pages 500** | DB unreachable (readiness masks it) | **Database** below |
| Errors mention DB / disk / connection slots | Postgres / migration | **Database** below |

## Backend (`trainsight-app`)

```bash
az webapp show -n trainsight-app -g rg-trainsight --query state -o tsv   # Running?
az webapp log tail -n trainsight-app -g rg-trainsight                    # live logs
az webapp restart -n trainsight-app -g rg-trainsight                     # first lever
```

App Insights (Logs blade) — recent failures + the known Garmin storm signal:
```kql
exceptions | where timestamp > ago(1h) | summarize count() by type, outerMessage | top 20 by count_
AppTraces | where timestamp > ago(2h)
  | where Message has "All login strategies exhausted" or Message has "IP rate limited by Garmin"
```

## Frontend (`praxys-frontend`)

```bash
az webapp show -n praxys-frontend -g rg-trainsight --query state -o tsv
az webapp restart -n praxys-frontend -g rg-trainsight
```

## Database (`praxys-pg`, Postgres)

Liveness `/api/health` returns 200 even when the DB is down — **check
readiness**, which runs a real `SELECT 1`:

```bash
curl -s https://api.praxys.run/api/health/ready   # ready 200  vs  503 {"database":"error"}
```

A 503 here means the app can't reach Postgres. Most often it's **connection
exhaustion**, not a server outage.

### Connection exhaustion (the 2026-07-05 outage)

**Signature:** readiness 503; App Insights `exceptions` show
`OperationalError ... FATAL: remaining connection slots are reserved for roles
with the SUPERUSER attribute`. The Burstable **B1ms** server has
`max_connections=50` with ~15 reserved → only **~35 usable by the app**. Near
that ceiling new app logins are refused and every data endpoint 500s.

**Diagnose** (`$PG` = the praxys-pg resource ID):

```bash
az postgres flexible-server show -g rg-trainsight -n praxys-pg --query state -o tsv   # usually "Ready" — it is a client-side connection problem
az monitor metrics list --resource "$PG" --metric active_connections --interval PT1M --aggregation Maximum --query "value[0].timeseries[0].data[-10:]" -o json   # pegged near 50?
az monitor app-insights query --app appi-praxys-backend --analytics-query "exceptions | where timestamp > ago(1h) | where outerMessage has 'remaining connection slots' | count"
```

**Mitigate — in order:**

1. `az webapp restart -n trainsight-app -g rg-trainsight`. **Often does NOT
   help:** connections abandoned by prior container cycles linger idle
   server-side and survive an app restart. Watch `active_connections`; if it
   doesn't drop within a minute, go to step 2.
2. **Restart Postgres** — the decisive lever; hard-resets every backend:
   ```bash
   az postgres flexible-server restart -g rg-trainsight -n praxys-pg
   ```
   ~1 min of DB downtime, acceptable when the service is already fully down. You
   **can't** surgically `pg_terminate_backend()` — only superuser-reserved slots
   remain, so even an Entra-admin login is refused. Verify readiness → 200 and
   `active_connections` drops below ~15.

**Prevent / root cause:** abandoned SQLAlchemy pools pile up as idle "zombie"
backends across container recycles (worsened by a per-tick `init_db()` that
rebuilt the pool). Fixed by disposing engines on shutdown + idempotent
`init_db()` (`db/session.py`), `alwaysOn=true` (fewer recycles), and the
`praxys-pg-connections-high` early-warning alert. Budget + tuning:
[config-and-secrets.md](./config-and-secrets.md).

### Corruption / bad migration

- A boot crash-loop citing the DB is usually a bad migration — check boot logs
  (`az webapp log tail`) for `init_db` / Alembic errors.
- Corruption suspected → [backup-and-restore.md](./backup-and-restore.md).

## Escalate / rollback

- Bad deploy → revert on `main` or re-tag a good build ([deploy.md](./deploy.md)).
- Can't resolve quickly → restart buys time; restore from backup if data is at risk.

## Verify

Health endpoints green; error rate back to baseline in App Insights; spot-check a
user dashboard.

## Related

- [deploy.md](./deploy.md) · [sync-troubleshooting.md](./sync-troubleshooting.md) · [monitoring-and-alerts.md](./monitoring-and-alerts.md)

---
_Last reviewed: 2026-07-05 · Owner: @dddtc2005 · TODO(@dddtc2005): define severity levels + escalation contacts._
