# Service status page & incident management

> **Summary:** How the public status page (`/status`) reports health, and how an
> admin declares, updates, and resolves a service incident.
> **Use when:** You need to tell users about an outage/degradation, or you want
> to understand what drives the status banner.

## What the status page shows

`https://www.praxys.run/status` is **public** (no login) — reachable even when a
user cannot sign in, which is the point of a status page. It renders:

1. **An overall banner** — the worst of automated component health and any
   active (unresolved) incident.
2. **Component health** — probed live on each request by `GET /api/status`:
   - **API** — always operational if the request is served.
   - **Database** — `SELECT 1` (same probe as `/api/health/ready`); a failure
     shows `major_outage` but the endpoint still returns 200 so the page renders.
   - **Background Sync** — the sync scheduler thread. Operational when alive or
     when intentionally disabled (`PRAXYS_SYNC_SCHEDULER=false`); `degraded` only
     when it is expected-but-dead.
3. **Active incidents** and **past (resolved) incidents**, each with a timeline.

Severity mapping (worst wins → overall banner):

| Source | → overall |
|---|---|
| component `degraded_performance` / incident impact `minor` | `degraded` |
| component `partial_outage` / incident impact `major` | `partial_outage` |
| component `major_outage` / incident impact `critical` | `major_outage` |

Incident **title/body copy is operator-authored English** (like GitHub Status);
the page *chrome* (labels) is localized (en/zh).

## Prerequisites

- An **admin** account (`is_superuser=True`). Incident management lives on the
  `/admin/incidents` route.
- No Azure/infra access needed: incidents are DB rows, read fresh per request.
  No new secret, resource, or alert is involved.

## Steps

1. **Open an incident.** `/admin/incidents` → **New incident**:
   set a **title**, pick an **impact** (`minor` | `major` | `critical`), add an
   optional opening message, then **Open incident**. It appears immediately on
   `/status` and drives the banner.
2. **Post progress updates.** On the incident row, type an update message and
   click **Identified** or **Monitoring** to transition status with a timeline
   entry. (A blank message gets a sensible default.)
3. **Resolve.** Click **Resolve** — stamps `resolved_at`, drops the incident out
   of the active banner, and files it under *Past incidents*.
4. **Correct / remove.** Fix a `title`/`impact` typo with `PATCH
   /api/admin/incidents/{id}`; delete a mistaken incident with the trash icon
   (cascades to its updates).

Equivalent API (all admin-only except the two public reads):

```
GET    /api/status                        # public: overall + components + active incidents
GET    /api/status/incidents?limit=20     # public: recent history
GET    /api/admin/incidents               # admin: management list
POST   /api/admin/incidents               # admin: open (seeds first update)
POST   /api/admin/incidents/{id}/updates  # admin: append update, optional status transition
PATCH  /api/admin/incidents/{id}          # admin: edit title / impact
DELETE /api/admin/incidents/{id}          # admin: delete
```

## Verify

- Open `https://www.praxys.run/status` in a private window (logged out) and
  confirm the incident + banner render. The page auto-refreshes every 30s.
- `curl -s https://api.praxys.run/api/status | jq '.overall, .incidents[].title'`.

## Rollback / Recovery

- **Reopen** a prematurely-resolved incident: post an update with a non-resolved
  status (`investigating`/`identified`/`monitoring`) — `resolved_at` is cleared.
- **Remove** an incident posted in error: delete it (trash icon / `DELETE`).
- The status page is read-only over real infra; nothing here changes App Service,
  secrets, or Azure resources.

## Related

- Backend: `api/routes/status.py`, models `ServiceIncident` /
  `ServiceIncidentUpdate` in `db/models.py`, probe `db/sync_scheduler.scheduler_running`.
- Frontend: public page `web/src/pages/Status.tsx` (`/status` route in
  `web/src/App.tsx`), admin UI in `web/src/pages/admin/AdminIncidents.tsx`.
- Related runbooks: [incident-response.md](./incident-response.md) (first-response
  triage when the app is actually down), [admin-tasks.md](./admin-tasks.md).

---
_Last reviewed: 2026-07-17 · Owner: @dddtc2005_
