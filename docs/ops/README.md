# Praxys Operations Handbook

Operational runbooks and troubleshooting guides (TSGs) for running Praxys in
production. This is the single entry point for "how do I configure / deploy /
diagnose X". It complements — and links out to — the setup-oriented
[`docs/deployment.md`](../deployment.md).

> **For AI agents:** every runbook follows [`_TEMPLATE.md`](./_TEMPLATE.md) — a
> one-line *Summary*, a **Use when** line, then `Prerequisites · Steps · Verify ·
> Rollback / Recovery · Related`. Parse the **Use when** line of each runbook in
> the index below to route a task; the `## Steps` blocks are copy-pasteable.

## Runbook index

| Runbook | Use when |
|---|---|
| [environment.md](./environment.md) | You need the canonical Azure resource names / IDs / hostnames. |
| [config-and-secrets.md](./config-and-secrets.md) | You're adding, changing, or rotating an env var / secret / variable, and need to know **where** it's set. |
| [deploy.md](./deploy.md) | You're deploying the backend, frontend, or mini program — or need to roll back. |
| [org-migration.md](./org-migration.md) | Migrating the repos from `dddtc2005` into the `praxys-run` org (OIDC pre-stage, App reinstall, tokens). |
| [monitoring-and-alerts.md](./monitoring-and-alerts.md) | You want to query a telemetry signal or wire an email/Teams alert. |
| [admin-tasks.md](./admin-tasks.md) | You're doing an in-app admin task: invitations, roles, demo accounts, announcements, feedback triage. |
| [setup-github-app.md](./setup-github-app.md) | Setting up feedback → GitHub issue filing (GitHub App auth — no token to rotate). |
| [change-loop.md](./change-loop.md) | Operating the change loop (Loop A): the `agent-ready` label that hands a qualifying bug to the Copilot coding agent. |
| [incident-response.md](./incident-response.md) | The app is down / erroring and you need first-response triage. |
| [status-page.md](./status-page.md) | You need to declare / update / resolve an incident on the public status page (`/status`). |
| [sync-troubleshooting.md](./sync-troubleshooting.md) | A user's data stopped updating or a connection shows `auth_required`. |
| [backup-and-restore.md](./backup-and-restore.md) | You need to back up or restore the database. |
| [postgres-migration.md](./postgres-migration.md) | You are migrating the database from SQLite to Azure Postgres (#360), or provisioning Postgres. |
| [secret-rotation.md](./secret-rotation.md) | Rotating a secret (JWT, WeChat, feedback App key, Key Vault key). |
| [cost-and-scaling.md](./cost-and-scaling.md) | Setting cost guardrails or scaling the backend. |
| [disaster-recovery.md](./disaster-recovery.md) | Rebuilding the whole deployment from scratch + restoring data. |

## Environment at a glance

| | |
|---|---|
| Subscription | `3ff02750-211c-4579-94a6-8c9af4e6d891` |
| Resource group | `rg-trainsight` |
| Backend (API) | App Service `trainsight-app` → `api.praxys.run` |
| Frontend (SPA) | App Service `praxys-frontend` → `www.praxys.run` |
| Secrets at rest | Key Vault `kv-trainsight` (RSA key `credential-encryption-key`) |
| Observability | Application Insights (signals prefixed `praxys.`) |

Full detail: [environment.md](./environment.md).

## Conventions

- One runbook per operational task or failure mode. Keep it self-contained.
- Ground every claim in the repo or Azure reality — link the source file/workflow.
- Commands are copy-pasteable (`az` / `gh` / KQL). Note the auth each step needs.
- Mark anything not yet verified with `TODO(owner)` rather than guessing.

## Coverage & roadmap

Incident response, backup/restore, DR, secret rotation, scaling/cost, and sync
troubleshooting now have runbooks. Remaining open items (on-call/escalation
definitions, RPO/RTO targets, the Key Vault re-wrap drill, optionally exposing
runbooks as a `plugins/praxys` skill) are tracked in **praxys-run/praxys#338** and
flagged inline as `TODO(@dddtc2005)`. Add new runbooks against
[`_TEMPLATE.md`](./_TEMPLATE.md) and link them from the index above.
