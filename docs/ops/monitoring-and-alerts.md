# Monitoring & alerts

> **Summary:** The Praxys telemetry signals, how to query them, and how to wire
> an email/Teams alert (worked example: feedback awaiting triage).
> **Use when:** You want to graph a signal, investigate spend/errors, or get
> notified when something needs attention.

## Telemetry model

The backend ships traces, request/dependency timings, and Python logs to
**Application Insights** automatically when `APPLICATIONINSIGHTS_CONNECTION_STRING`
is set (it is in prod; on App Service the app authenticates via its managed
identity — see `api/main.py`). No PII is emitted in custom signals — only
low-cardinality dimensions.

Custom signals are emitted by `api/telemetry.py`. Each lands as either:
- a **customEvent** with that name (when the optional
  `azure-monitor-events-extension` is installed), **or**
- a **customMetric** counter with that name (the default).

Queries below `union` both shapes so they work either way.

## Signals

| Signal | Dimensions | Meaning | Emitter |
|---|---|---|---|
| `praxys.coach_tokens` | `insight_type`, `model`, `token_type` | Azure OpenAI tokens consumed (spend) | `record_coach_tokens` |
| `praxys.coach_run` | `insight_type`, `status`, `user_id_hash` | Insight-runner outcomes (cache hit rate) | `record_coach_run` |
| `praxys.coach_error` | `error_class` | Operator-actionable Coach errors (Auth/BadRequest) | `record_coach_error` |
| `praxys.feedback` | `kind`, `status` | In-app feedback submissions + triage outcomes | `record_feedback` |
| `praxys.db_health` | `status`, `backend` | DB integrity/connectivity failures (startup check + readiness probe) | `record_db_health` |

> `praxys.feedback` is added by the feedback feature (dddtc2005/praxys#328). Once
> merged, its `status` dimension includes `needs_review` — the trigger for the
> alert below.

## Querying (Logs blade → KQL)

Daily LLM token spend by surface:
```kql
customMetrics
| where name == "praxys.coach_tokens"
| extend insight_type = tostring(customDimensions.insight_type),
         token_type = tostring(customDimensions.token_type)
| where token_type == "total"
| summarize tokens = sum(valueSum) by insight_type, bin(timestamp, 1d)
```

Coach cache-hit rate (last 7d):
```kql
customMetrics | where name == "praxys.coach_run"
| extend status = tostring(customDimensions.status)
| summarize hits = countif(status == "hash_match"), total = count()
| extend hit_rate = todouble(hits) / total
```

Active users (DAU / WAU) of registered accounts. The SPA tags telemetry with
`user_AuthenticatedId` = a SHA-256(user_id)[:16] pseudonym (set on login by
`web/src/lib/appinsights.ts`, matching `api/telemetry.py::hash_user_id`), so this
counts distinct *registered* users — not anonymous browsers — and correlates with
the backend `praxys.*` events. Only authenticated navigation is counted (the
anonymous landing page is excluded); demo accounts are included.
```kql
// WAU (last 7d) and DAU trend (last 30d)
pageViews
| where timestamp > ago(7d)
| where isnotempty(user_AuthenticatedId)
| summarize wau = dcount(user_AuthenticatedId)

pageViews
| where timestamp > ago(30d)
| where isnotempty(user_AuthenticatedId)
| summarize dau = dcount(user_AuthenticatedId) by bin(timestamp, 1d)
| render timechart
```

## Create an email alert (general recipe)

1. **Application Insights → Monitoring → Alerts → Create → Alert rule.**
2. **Scope:** the Praxys Application Insights resource.
3. **Condition → Custom log search:** paste a KQL query that returns rows only
   when you want to fire. Measurement = **Number of results**, **> 0**, evaluated
   every 15 minutes over a 15-minute window.
4. **Actions:** attach an **Action group** with an **Email** action (Teams /
   webhook / SMS also available here). Reuse one action group across alerts.
5. **Details:** name + severity (Sev 3 for "needs attention", Sev 1 for outage).

## Worked example — feedback awaiting triage (`needs_review`)

When a feedback report can't be auto-filed safely it's parked as `needs_review`
(shown as an Admin-sidebar badge in-app). To also email admins:

```kql
union isfuzzy=true
  (customMetrics
    | where name == "praxys.feedback"
    | extend status = tostring(customDimensions.status)),
  (customEvents
    | where name == "praxys.feedback"
    | extend status = tostring(customDimensions.status))
| where status == "needs_review"
```

Wire it per the recipe above (results > 0, every 15 min, Sev 3, email action
group). To also catch publish failures use
`where status in ("needs_review", "failed")`.

**Verify:** submit a test report that trips the gate (e.g. with `AZURE_AI_ENDPOINT`
unset, or paste a fake `sk-...` token) and confirm the email within ~15 min.

## Database health alert (#350) — WIRED

`praxys.db_health` fires from the startup integrity check (`db/session.py`) and
the `/api/health/ready` probe when the database is corrupt or unreachable - the
gap that made the 2026-07-03 corruption *and* the 2026-07-05 connection-
exhaustion outage invisible to the liveness-only `/api/health` (nothing was
watching the readiness 503).

Live as scheduled-query rule **`praxys-db-health-unhealthy`** (Sev 1, every
5 min, action group `praxys-feedback-ag`):

```kql
union isfuzzy=true
  (customMetrics | where name == "praxys.db_health"
    | extend status = tostring(customDimensions.status)),
  (customEvents  | where name == "praxys.db_health"
    | extend status = tostring(customDimensions.status))
| where status in ("integrity_failed", "check_error", "readiness_failed")
```

Recreate it with (collapse the KQL above onto one line as `<KQL>`):

```bash
AI=$(az monitor app-insights component show -g rg-trainsight --query "[0].id" -o tsv)
AG=$(az monitor action-group show -g rg-trainsight -n praxys-feedback-ag --query id -o tsv)
az monitor scheduled-query create -g rg-trainsight -n praxys-db-health-unhealthy --scopes "$AI" --condition "count 'q' > 0" --condition-query "q=<KQL>" --evaluation-frequency 5m --window-size 5m --severity 1 --action-groups "$AG"
```

## Postgres connection-pressure alert — WIRED

Catches the *cause* one layer before the readiness 503. Burstable B1ms allows
`max_connections=50` (~35 usable by the app after reserved slots); healthy
baseline is <15. Live as metric alert **`praxys-pg-connections-high`** (Sev 2,
avg `active_connections` > 40 over 5 min, `praxys-feedback-ag`):

```bash
PG=$(az postgres flexible-server show -g rg-trainsight -n praxys-pg --query id -o tsv)
AG=$(az monitor action-group show -g rg-trainsight -n praxys-feedback-ag --query id -o tsv)
az monitor metrics alert create -g rg-trainsight -n praxys-pg-connections-high --scopes "$PG" --condition "avg active_connections > 40" --window-size 5m --evaluation-frequency 5m --severity 2 --action "$AG"
```

> **Health-check caveat (single instance).** Do **not** wire `/api/health/ready`
> as the App Service *health-check path* on this single-instance backend: a
> DB-down readiness failure would trigger health-check-driven container
> restarts, and each restart abandons its connection pool — *amplifying* a
> connection-exhaustion event instead of mitigating it (see the 2026-07-05
> outage in [incident-response.md](./incident-response.md)). The two alerts
> above page a human instead. Revisit only at ≥2 instances, where a health
> check removes a bad instance from rotation without a restart storm.

## Rollback / Recovery

Alerts are non-destructive — disable or delete the alert rule to stop emails.
Tune the window/threshold to reduce noise rather than deleting.

## Related

- `api/telemetry.py` (signal emitters) · [admin-tasks.md](./admin-tasks.md) (feedback triage)
- In-app: Admin → User Feedback (badge + Approve/Retry/Reject).

---
_Last reviewed: 2026-07-05 · Owner: @dddtc2005_
