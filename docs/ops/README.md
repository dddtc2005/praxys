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
| [monitoring-and-alerts.md](./monitoring-and-alerts.md) | You want to query a telemetry signal or wire an email/Teams alert. |
| [admin-tasks.md](./admin-tasks.md) | You're doing an in-app admin task: invitations, roles, demo accounts, announcements, feedback triage. |

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

This is **v1**. Incident response, backup/restore, DR, deep secret-rotation,
scaling, cost, and sync troubleshooting are tracked in the handbook issue:
**dddtc2005/praxys#338**. Add new runbooks against [`_TEMPLATE.md`](./_TEMPLATE.md)
and link them from the index above.
