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

## Rollback / Recovery

Alerts are non-destructive — disable or delete the alert rule to stop emails.
Tune the window/threshold to reduce noise rather than deleting.

## Related

- `api/telemetry.py` (signal emitters) · [admin-tasks.md](./admin-tasks.md) (feedback triage)
- In-app: Admin → User Feedback (badge + Approve/Retry/Reject).

---
_Last reviewed: 2026-06-30 · Owner: @dddtc2005_
