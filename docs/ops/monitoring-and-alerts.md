# Monitoring & alerts

> **Summary:** The Praxys telemetry signals, how to query them, the live **alert
> inventory + cost model**, and how to add or tune an alert without overspending.
> **Use when:** You want to graph a signal, investigate spend/errors, add or tune
> an alert, or get notified when something needs attention.

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

> `praxys.feedback`'s `status` dimension includes `needs_review` — the trigger for
> the feedback alert below.

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

## Alert inventory (source of truth)

Every rule below lives in `rg-trainsight` (region **eastasia**) and routes to the
`praxys-feedback-ag` action group (→ `support@praxys.run`). Costs are the eastasia
retail rate per the [cost model](#alert-cost-model) below.

| Rule | Type | Watches | Eval | Sev | ~USD/mo |
|---|---|---|---|---|---|
| `praxys-db-health-unhealthy` | log | `praxys.db_health` failure (corrupt/unreachable DB) | 5 min | 1 | **1.50** |
| `praxys-pg-connections-high` | metric | `praxys-pg` `active_connections` avg > 40 | 5 min | 2 | ~0.10 |
| `wt-praxys-homepage` | metric (web test) | `https://www.praxys.run/` reachable | 1 min | 1 | ~0.10 |
| `wt-praxys-api-health` | metric (web test) | `.../api/health` reachable | 1 min | 1 | ~0.10 |
| `praxys-feedback-needs-review` | log | `praxys.feedback` `status == needs_review` | 15 min | 3 | 0.50 |
| `praxys-today-latency-regression` | log | `GET /api/today` avg latency > 3000 ms | 1 h | 3 | 0.50 |

**Total ≈ 2.5–2.8 USD/mo** (the three metric alerts may fall inside the small free
allotment, making the effective figure closer to the 2.50 log-alert subtotal).

> **Currency rule.** Any PR that adds, removes, or re-tunes an alert **must update
> this table in the same PR** — rule name, what it watches, eval frequency,
> severity, and cost. This table is the source of truth; the Azure portal is not.

Verify the live state at any time:
```bash
az monitor scheduled-query list -g rg-trainsight \
  --query "[].{name:name,enabled:enabled,sev:severity,freq:evaluationFrequency,hasAG:length(actions.actionGroups)}" -o table
az monitor metrics alert list -g rg-trainsight \
  --query "[].{name:name,enabled:enabled,sev:severity,freq:evaluationFrequency,hasAG:length(actions)}" -o table
```

## Alert cost model

Azure Monitor bills alert rules three different ways — knowing which lever exists
prevents "optimisations" that save nothing. Prices are **eastasia retail**
(via the Retail Prices API; re-check as they change):

```bash
curl -s "https://prices.azure.com/api/retail/prices?\$filter=serviceName%20eq%20'Azure%20Monitor'%20and%20armRegionName%20eq%20'eastasia'%20and%20contains(meterName,'Alert')" | jq '.Items[] | {meterName,unitPrice} '
```

| Alert type | Billed on | eastasia price |
|---|---|---|
| **Log** (scheduled query) | evaluation frequency | 1 min **3.00** · 5 min **1.50** · 10 min **1.00** · **≥15 min 0.50 (floor)** — per rule/mo |
| **Metric** (incl. web-test availability) | monitored time-series | **~0.10** per series/mo, **frequency-independent** (small free allotment) |
| **Metric, dynamic threshold** | monitored time-series | ~2× the static rate |
| **Standard web test execution** | per execution | **0.00** in eastasia (free grant) |

Three rules that follow from the table:

1. **The log-alert floor is 15 min.** Every frequency of 15 min or slower bills at
   the same **0.50**. Slowing a log alert from 15 min to hourly (or daily) saves
   **nothing** — pick that frequency for signal quality, not cost.
2. **Only sub-15-min log alerts cost more.** 5 min = 3× the floor, 1 min = 6×.
   Spend that premium **only where detection latency matters** (a Sev 1 outage).
   Today the sole example is `praxys-db-health-unhealthy` (5 min, +~1.00/mo over the
   floor) — justified: it's the detector for the DB-corruption (2026-07-03) and
   connection-exhaustion (2026-07-05) outages that were previously invisible.
3. **Metric-alert frequency is free.** A 1-min metric alert costs the same as a
   15-min one. When a *metric* signal exists and you want fast detection, a metric
   alert is both cheaper and faster than a log alert.

> Tempting but rejected: re-expressing `praxys.db_health` as a metric alert (flat
> ~0.10, could even run at 1 min) to shave the log premium. `record_db_health`
> emits a customEvent **or** customMetric opportunistically, so a metric alert
> would silently go blind if `azure-monitor-events-extension` is ever installed —
> too fragile for the highest-severity signal. Keep it a log alert.

## Severity & frequency (SLA guidance)

| Severity | Meaning | Recommended shape | Rationale |
|---|---|---|---|
| **Sev 1** | Outage — page a human now | metric alert (any freq) *or* log @ 5 min | MTTD matters; pay the log premium only when no metric signal exists |
| **Sev 2** | Early warning — head off an outage | metric @ ≤5 min (freq is free) *or* log @ 15 min | catch the *cause* one layer before the symptom |
| **Sev 3** | Needs attention, not urgent | log @ 15 min–1 h | all at the 0.50 floor — choose for noise/signal, not cost |

## Adding monitoring — guidance for developers & AI agents

When you add or change a feature, treat monitoring as part of "done":

1. **Does it have an operator-actionable failure mode?** (a sync that can wedge, a
   dependency that can 5xx, a budget that can blow.) If yes, it needs a signal.
2. **Emit through `api/telemetry.py`** — low-cardinality dimensions, **no PII**
   (hash user ids via `hash_user_id`). Prefer a **failure-only** counter (like
   `record_db_health`) so a plain `count > 0` alert works without dimension
   gymnastics.
3. **Pick the alert type from the [cost model](#alert-cost-model):** a metric
   signal that needs fast MTTD → **metric alert** (flat, cheap, any frequency); a
   query that needs KQL or multi-signal correlation → **log alert** (respect the
   0.50 floor; don't go below 5 min unless it's Sev 1).
4. **Wire an action group.** An alert with no action group evaluates but **pages
   nobody** — a silent no-op (three Praxys alerts were in this state until
   2026-07-05). Reuse `praxys-feedback-ag`.
5. **Set severity per the SLA table** — don't over-page (Sev 1 wakes someone).
6. **Update the [inventory table](#alert-inventory-source-of-truth) in the same
   PR** (currency rule).
7. **Keep an alert and its underlying probe in the same enabled state** — a running
   web test whose alert is disabled pays to watch nothing; a disabled probe with a
   live alert never fires.

## Create an alert (general recipe)

1. **Application Insights → Monitoring → Alerts → Create → Alert rule.**
2. **Scope:** the Praxys Application Insights resource (or `praxys-pg` for DB metrics).
3. **Condition → Custom log search:** paste a KQL query that returns rows only
   when you want to fire. Measurement = **Number of results**, **> 0**. Choose the
   evaluation frequency with the cost model in mind (15 min is the log floor; go to
   5 min only for Sev 1).
4. **Actions:** attach the **`praxys-feedback-ag`** action group (Email; Teams /
   webhook / SMS also available). **Don't skip this** — an action-less alert is a
   no-op.
5. **Details:** name + severity (Sev 3 "needs attention", Sev 1 outage), then record
   the rule in the inventory table above.

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

Wired as `praxys-feedback-needs-review` (results > 0, every 15 min, Sev 3,
`praxys-feedback-ag`). To also catch publish failures use
`where status in ("needs_review", "failed")`.

**Verify:** submit a test report that trips the gate (e.g. with `AZURE_AI_ENDPOINT`
unset, or paste a fake `sk-...` token) and confirm the email within ~15 min.

## Alert deep-dives

### Database health — `praxys-db-health-unhealthy` (#350)

`praxys.db_health` fires from the startup integrity check (`db/session.py`) and
the `/api/health/ready` probe when the database is corrupt or unreachable — the
gap that made the 2026-07-03 corruption *and* the 2026-07-05 connection-
exhaustion outage invisible to the liveness-only `/api/health`. Sev 1, every
5 min (the one justified sub-floor log premium — see cost model).

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

### Postgres connection pressure — `praxys-pg-connections-high`

Catches the *cause* one layer before the readiness 503. Burstable B1ms allows
`max_connections=50` (~35 usable by the app after reserved slots); healthy
baseline is <15. Sev 2, avg `active_connections` > 40 over 5 min. Metric alert,
so the 5-min frequency is free.

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
> outage in [incident-response.md](./incident-response.md)). The alerts page a
> human instead. Revisit only at ≥2 instances, where a health check removes a
> bad instance from rotation without a restart storm.

### `/api/today` latency regression — `praxys-today-latency-regression`

Sev 3 scheduled query, evaluated hourly over a 24 h window. Fires when the
`GET /api/today` average server duration drifts above 3000 ms (post-PR-139
baseline ~1900 ms; the `n >= 5` guard avoids noise on low-traffic days). At 1 h
eval it bills at the 15-min 0.50 floor.

```kql
requests
| where name == 'GET /api/today'
| summarize avg_ms = avg(duration), n = count()
| where n >= 5 and avg_ms > 3000
```

```bash
AI=$(az monitor app-insights component show -g rg-trainsight --query "[0].id" -o tsv)
AG=$(az monitor action-group show -g rg-trainsight -n praxys-feedback-ag --query id -o tsv)
az monitor scheduled-query create -g rg-trainsight -n praxys-today-latency-regression --scopes "$AI" --condition "count 'q' > 0" --condition-query "q=<KQL>" --evaluation-frequency 1h --window-size 24h --severity 3 --action-groups "$AG"
```

### External availability — `wt-praxys-homepage`, `wt-praxys-api-health`

Two **Standard availability tests** ping outside-in every 15 min (30 s timeout)
from **US-West (San Jose, `us-ca-sjc-azr`)** and **APAC (Hong Kong,
`apac-hk-hkn-azr`)** — the vantages that match the audience (US + CN/APAC). Each
has an auto-created **metric alert** (Sev 1, `praxys-feedback-ag`) that fires when
**≥1 location** reports failure. This is black-box coverage that complements the
inside-the-process db-health / readiness probes.

| Web test | Target |
|---|---|
| `wt-praxys-homepage` | `https://www.praxys.run/` |
| `wt-praxys-api-health` | `https://trainsight-app.azurewebsites.net/api/health` |

Standard web-test execution is **0.00** in eastasia (free grant); the two alerts
are cheap metric alerts. **Keep each web test and its alert in the same enabled
state** — a probe that runs while its alert is disabled pays to watch nothing
(found and fixed 2026-07-05). Re-point locations via the availability test's
*Locations* in the portal or `az resource update`.

## Rollback / Recovery

Alerts are non-destructive — disable or delete the rule to stop notifications.
To cut cost, remember the log floor: dropping a log alert below 15 min is the only
frequency change that saves money; slowing one past 15 min saves nothing. To cut
noise, tune the window/threshold rather than deleting. Update the inventory table
after any change.

## Related

- `api/telemetry.py` (signal emitters) · [cost-and-scaling.md](./cost-and-scaling.md) (budget + LLM spend) · [admin-tasks.md](./admin-tasks.md) (feedback triage)
- In-app: Admin → User Feedback (badge + Approve/Retry/Reject).

---
_Last reviewed: 2026-07-05 · Owner: @dddtc2005 · Alert inventory + cost model current as of this review._