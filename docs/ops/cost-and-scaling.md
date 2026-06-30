# Cost & scaling

> **Summary:** Watch spend and scale the backend when load grows.
> **Use when:** Setting up cost guardrails, investigating a bill, or the app is
> resource-constrained.

## Cost guardrails

- **Azure budget + alert** on `rg-trainsight` (one-time):
  ```bash
  az consumption budget create --budget-name praxys-monthly \
    --amount 50 --time-grain Monthly --category Cost \
    --resource-group rg-trainsight   # adjust amount; add notifications in the portal
  ```
- **LLM spend** is the main variable cost. Track it via the `praxys.coach_tokens`
  signal ([monitoring-and-alerts.md](./monitoring-and-alerts.md)) and the per-user
  daily cap `PRAXYS_INSIGHT_DAILY_CAP` (default 30). Lower the cap to throttle.
- Standing infra is small: App Service plan `plan-trainsight` (B1) hosts both
  backend + frontend at $0 incremental; perf-baseline storage is ~$0.05/mo idle.

## Scaling the backend

Default is a single **B1** instance. Options when constrained:

```bash
# Scale UP (bigger instance) — simplest, no scheduler caveat
az appservice plan update -n plan-trainsight -g rg-trainsight --sku P1V3

# Scale OUT (more instances)
az appservice plan update -n plan-trainsight -g rg-trainsight --number-of-workers 2
```

**Scale-out caveat (important):** each worker runs its own background **sync
scheduler** (`db/sync_scheduler.py`, started per-worker in `api/main.py`).
Per-row `last_sync` checks make duplicate ticks idempotent, but to run exactly
one scheduler set `PRAXYS_SYNC_SCHEDULER=false` on N-1 workers, or keep a
single-worker deployment. Verify behaviour before relying on multi-worker.

Note: scale-up resets App Service local state on the new instance — `/home`
persists (the DB is safe), but in-memory sync status resets.

## Verify

`az appservice plan show -n plan-trainsight -g rg-trainsight --query sku`.
Watch CPU/memory in the App Service "Metrics" blade after the change.

## Related

- [monitoring-and-alerts.md](./monitoring-and-alerts.md) · [environment.md](./environment.md)

---
_Last reviewed: 2026-06-30 · Owner: @dddtc2005 · TODO(@dddtc2005): set the real budget amount + when-to-scale thresholds._
