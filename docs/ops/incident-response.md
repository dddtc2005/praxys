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
| Errors mention DB / disk | storage / migration | **Database** below |

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

## Database

- `/home` is persistent; a crash loop citing the DB is usually a bad migration or
  a full `/home`. Check boot logs (`az webapp log tail`) for `init_db` errors.
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
_Last reviewed: 2026-06-30 · Owner: @dddtc2005 · TODO(@dddtc2005): define severity levels + escalation contacts._
