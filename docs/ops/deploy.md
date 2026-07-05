# Deploy & rollback

> **Summary:** How each surface (backend, frontend, mini program) deploys, how to
> trigger/re-run, and how to roll back.
> **Use when:** Shipping a change to prod, or reverting a bad deploy.

## How deploys trigger

| Surface | Workflow | Triggers | Target |
|---|---|---|---|
| Backend (API) | `deploy-backend.yml` | push to `main` touching `api/ analysis/ sync/ db/ data/science/ tests/ requirements.txt`; or `api-*` tag | App Service `trainsight-app` |
| Frontend (SPA) | `deploy-frontend-appservice.yml` | push to `main` touching `web/ frontend_server/`; or `web-*` tag | App Service `praxys-frontend` |
| Mini program | `miniapp-publish.yml` | `miniapp-YYYY.MM.MICRO` release tag (robot 1); `main` pushes auto-publish a dev build (robot 5) | WeChat (`miniprogram-ci`) |

All three authenticate to Azure / WeChat via OIDC or the upload key — no
passwords. Backend + frontend run their test/build gates **before** deploying.

**Pre-merge gate.** Before any deploy, `ci-backend.yml` runs the backend `pytest` suite on every PR to `main` and reports a **required** status check (`backend-tests`). A red suite blocks merge, so regressions never reach the deploy step (see [environment.md](./environment.md) → Repo governance). `deploy-backend.yml` re-runs the same suite post-merge as a deploy-time backstop.

## Backend deploy

Automatic on merge to `main` (for the paths above). The workflow:
1. Runs `pytest tests/`.
2. Stamps `api/_build_version.txt`.
3. OIDC login → **syncs App Service settings** (see [config-and-secrets.md](./config-and-secrets.md)) → `azure/webapps-deploy`.

Force a deploy without a code change: re-run the latest `deploy-backend.yml` run
(`gh run rerun <id>`), or push an `api-YYYY.MM.MICRO` tag for a versioned release.

## Frontend deploy

Automatic on merge touching `web/`. Builds `web/dist/` with `VITE_API_URL` baked
in, packages it with `frontend_server/`, deploys to `praxys-frontend`.

## Mini program

Tag-driven CalVer — see the **"How to release the mini program"** runbook in
[`CLAUDE.md`](../../CLAUDE.md). Promoting 体验版 → 提交审核 → 发布 stays manual in
mp.weixin.qq.com (no first-party API).

## Verify

```bash
curl -s https://api.praxys.run/api/health      # {"status":"ok"}
curl -s https://api.praxys.run/api/version     # {"version":"YYYY.MM.DD..."}
curl -s -o /dev/null -w "%{http_code}\n" https://www.praxys.run/healthz   # 200
```

Watch a run to completion:
```bash
gh run watch "$(gh run list --workflow=deploy-backend.yml --limit 1 --json databaseId --jq '.[0].databaseId')" --exit-status
```

## Rollback / Recovery

There are **no deployment slots** on the B1 plan, so rollback = re-deploy a known
-good revision:

1. **Revert the commit** on `main` (`git revert <sha> && git push`) — the deploy
   workflow re-runs and ships the reverted state. Safest for app bugs.
2. **Re-tag a prior good commit** (`api-*` / `web-*`) to redeploy that exact build.
3. **Schema note:** migrations are additive / non-destructive — `init_db()` runs
   `alembic upgrade head`, which adds tables/columns and may tweak constraints
   (e.g. adding `ON DELETE SET NULL` to a foreign key, #366) but does not drop
   tables/columns or data. A code rollback won't undo an applied migration, and
   that's safe: old code ignores added columns, and a data-preserving constraint
   change is transparent to it. A genuinely *destructive* schema change would
   need a forward-fix, not a rollback.

> Config-only revert (a bad App Service setting): fix the GitHub secret/variable
> and re-deploy — don't hand-edit the portal (it's overwritten next deploy).

## Related

- [config-and-secrets.md](./config-and-secrets.md) · [monitoring-and-alerts.md](./monitoring-and-alerts.md)
- `docs/deployment.md` (one-time Azure setup) · `.github/workflows/`

---
_Last reviewed: 2026-07-05 · Owner: @dddtc2005_
