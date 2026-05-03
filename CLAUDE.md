# CLAUDE.md

## What This Is

Power-based scientific training system for self-coached endurance athletes. Syncs data from Garmin, Stryd, and Oura Ring, computes training metrics, and serves a modern web dashboard (FastAPI + React + SQLite) with weekly reports. Multi-user with JWT auth and invitation-based registration.

## Architecture

```
Garmin/Stryd/Oura APIs → sync/*.py → db/sync_writer.py → SQLite (trainsight.db)
                                                              ↓
                                                       analysis/metrics.py (pure computation)
                                                              ↓
                                                       api/deps.py (data layer)
                                                              ↓
                                                       api/routes/*.py (JSON endpoints, JWT auth)
                                                              ↓
                                                       web/ (React SPA)
```

### Module Map

| Directory | Owns | Key Files |
|-----------|------|-----------|
| `sync/` | Platform fetch + parse | `garmin_sync.py`, `stryd_sync.py`, `oura_sync.py`, `csv_utils.py`, `bootstrap_garmin_tokens.py` |
| `analysis/` | Metric computation | `metrics.py` (pure functions), `data_loader.py` (loads from DB), `science.py` (theory YAML loader), `config.py` (`UserConfig`), `zones.py`, `thresholds.py`, `training_base.py` |
| `analysis/providers/` | Pluggable data sources | `base.py` (ABCs), `garmin.py`, `stryd.py`, `oura.py`, `ai.py`, `models.py` |
| `db/` | SQLite layer | `models.py` (SQLAlchemy), `session.py`, `crypto.py` (Fernet credential encryption), `sync_writer.py` (upserts), `sync_scheduler.py` |
| `api/` | FastAPI backend | `main.py`, `deps.py` (data layer — `get_dashboard_data()`), `auth.py` (JWT), `users.py`, `views.py`, `invitations.py`, `routes/` (incl. `admin.py`, `register.py`, `wechat.py`) |
| `frontend_server/` | Static SPA host on its own App Service site (`praxys-frontend`) | `main.py` (`create_app(dist_dir)` factory, `SPAStaticFiles` with 404→`index.html` fallback for non-asset paths, cache-control middleware, `/healthz`). Decoupled from `api/` so the same `web/dist/` artifact can later sit on Tencent COS (CN audience, post-ICP) without Azure-specific glue. |
| `web/src/` | React SPA | `pages/` (Today, Training, Goal, History, Science, Settings, Admin, Login, Setup), `components/`, `hooks/`, `contexts/`, `types/api.ts`, `lib/` |
| `miniapp/` | WeChat Mini Program (native + Skyline + TypeScript) | `pages/` (login WebView, plus Skyline pages: today, training, goal, history, settings, science), `components/` (`nav-bar` custom Skyline header, `line-chart` Canvas 2D), `utils/` (`api-client.ts` wx.request + JWT, `auth.ts` wx.login flow, `format.ts`/`share.ts`/`theme.ts`), `types/api.ts` auto-synced from `web/src/types/api.ts` by `scripts/sync-types.cjs` (runs on `npm run typecheck`). Build: WeChat DevTools handles TypeScript + Sass via `project.config.json` `useCompilerPlugins` — no webpack/babel toolchain. Open `miniapp/` as the DevTools project root; only devDeps are `miniprogram-api-typings` + `typescript` for `tsc --noEmit` CI checks. **Mini program position**: a view + manage companion to the web app. New users register and run the platform-connection wizard on praxys.run; the mini program links an existing account by email/password and then handles day-to-day use (signal, training, goal, sync, theory, training-base, theme/language). The mini program login page surfaces a "new here? Sign up at praxys.run" row that copies the URL to clipboard rather than embedding the registration flow itself. |
| `plugins/praxys/` | Praxys plugin (**git submodule** of public [`dddtc2005/praxys-coach-plugin`](https://github.com/dddtc2005/praxys-coach-plugin), MIT) | `skills/` (8 SKILL.md), `mcp-server/` (local + remote MCP). Edits to anything inside `plugins/praxys/` are commits in the plugin repo, not this one — PRs there, then bump the submodule pointer here. |
| `tests/` | pytest suite | |
| `data/` | Fixtures + science YAML | `sample/` (test CSVs — not live data), `science/` (theory YAMLs) |
| `scripts/` | Utility + skill helpers | |
| `docs/` | User + dev docs | `docs/dev/` (architecture, API reference, design system, gotchas, contributing) |

### Data storage

Sync pipelines write directly to SQLite (`trainsight.db`) via `db/sync_writer.py` — there are no live CSVs. Tables: `activities`, `activity_splits`, `recovery_data`, `fitness_data`, `training_plans`, `users`, `user_config`, `user_connections`. `data/sample/` holds synthetic CSVs used only by tests and seed scripts.

## Scientific Rigor

All training metrics, predictions, and insights must be grounded in exercise science:
- **Cite sources** in code comments for formulas and constants (paper DOI or URL)
- **Show methodology** in the UI — use the `ScienceNote` component with source links
- **Use published values** over guesswork (Stryd race power percentages, Riegel, Banister TRIMP)
- **Flag estimates** — values without strong research backing noted as estimates in code and UI

## Gotchas

- **Activity `avg_power` is diluted** by warmup / cooldown / recovery jogs. Always use `activity_splits` for intensity analysis — `diagnose_training()` in `metrics.py` does this correctly.
- **Per-user Garmin tokenstore is load-bearing for security.** `sync/.garmin_tokens/<user_id>/` — `garminconnect.Garmin.login()` loads whatever OAuth tokens it finds without validating the account, so a shared directory would cross-leak authenticated sessions. Anything touching sync/auth must preserve this invariant.

Domain-specific gotchas (Garmin sync quirks, CIQ field conventions, CN endpoint parity, region model): `docs/dev/gotchas.md`.

## Conventions

### Python
- **Type hints** on every function signature; **docstrings** on public functions.
- `analysis/metrics.py` must be **pure** — no I/O, no side effects.
- All data loading goes through `analysis/data_loader.py`.
- API routes are thin wrappers around `get_dashboard_data()` in `api/deps.py`.
- Shared view helpers in `api/views.py` — used by routes and CLI skill scripts to avoid duplication.

### Frontend
- **TypeScript strict** — all API responses typed in `web/src/types/api.ts`.
- `useApi<T>` hook for data fetching (loading / error / data states).
- shadcn/ui + Tailwind v4. Never use raw hex — use CSS variables or `chartColors` from `@/lib/chart-theme.ts`.
- Every numeric value uses the `.font-data` class (JetBrains Mono, tabular-nums).
- **Semantic palette, not just accents**: `primary` (green) = action / positive signal; `accent-cobalt` is reserved for **reasoning** surfaces (`ScienceNote`, "why this", citations). Don't use cobalt for informational chrome and don't use green for reasoning.
- Authoritative brand guide: `docs/brand/index.html`. Implementation rules: `docs/dev/design-system.md`.

### Web ↔ miniapp parity
- **Frontend changes should reach both surfaces.** When you add or change a feature in `web/src/`, update the matching `miniapp/pages/` (or component / util) in the same PR — or open a follow-up issue with explicit "miniapp parity gap" labelling. Don't quietly let one client drift.
- The mini program is **not a desktop port** — it can adapt the layout / chrome / interactions to native mobile conventions, but the *feature set, data model, and write operations should match*. (Sync triggers, settings updates, goal config, language/theme switches, account management — all available on both.)
- Web is the canonical type source: `web/src/types/api.ts` → synced to `miniapp/types/api.ts` by `miniapp/scripts/sync-types.cjs` (runs on `npm run typecheck`).
- i18n catalogs are also web-canonical: lingui `.po` files in `web/src/locales/` → consumed by `miniapp/scripts/sync-i18n.cjs`. Add new translatable strings on the web side (or directly to a page's `t(...)` calls) — they propagate to the mini program at typecheck. Mini-only strings (login copy, modals, tooltips) live in `miniapp/utils/i18n-extra.ts` and override the synced catalog.
- **i18n coverage is enforced**: `miniapp/scripts/check-i18n.cjs` runs on `npm run typecheck` and fails CI if any WXML body / user-visible attribute / `t(...)` key has no zh entry, or if a hardcoded English-looking literal sneaks into a TS file. Wrap user-visible copy in `t()` / `tFmt()`; for mini-only strings add a `'key': '中文'` pair to `i18n-extra.ts` (both `en` and `zh` blocks). Same-line `// i18n-allow` opts an intentional literal out.
- Visual design **may diverge** between web and miniapp: web is a desktop-first React + shadcn surface; miniapp is a mobile-first Skyline surface with native-feeling chrome (custom nav bar, custom tab bar, FAB share buttons). Keep brand tokens (colors, typography intent, semantic palette) consistent; layout and interaction patterns can be platform-appropriate.

### Git
- **Commit / PR subjects state what the change does**, e.g. `Fix Garmin first-time sync…`. This repo is standalone (pushes to `dddtc2005/praxys`) — don't prefix with the folder name. The outer pensieve repo's `trail-running:` convention exists because that repo hosts multiple top-level projects; it doesn't apply here.
- Commit body explains the *why* (motivation, root cause, trade-off). The diff shows the *what*.
- Never put sensitive content (credentials, `.env` values, personal data) in commit messages or PR descriptions.

### API
- All endpoints under `/api/`. All require JWT auth (`Authorization: Bearer <token>`) except `/api/register` and `/api/token`.
- `get_dashboard_data()` recomputes all data fresh per request.
- User config stored in DB; platform credentials Fernet-encrypted via `db/crypto.py`.

## Dashboard Modes

Goal configuration stored in DB, managed via the Goal page:
- **Race Goal**: race date + optional target time + distance → countdown, predicted time, CP gap.
- **Continuous Improvement** (default): optional target time + distance → CP progress, milestones, trend.
- Distances: 5K, 10K, Half Marathon, Marathon, 50K, 50 Mile, 100K, 100 Mile.

## How to Add a New Metric

1. Pure function in `analysis/metrics.py` (type hints + docstring + source citation).
2. Call it from `get_dashboard_data()` in `api/deps.py`; add to returned dict.
3. Expose via the appropriate route in `api/routes/`.
4. Add TypeScript interface to `web/src/types/api.ts`.
5. Build a component in `web/src/components/`.
6. Wire into the relevant page in `web/src/pages/`.
7. Add a test in `tests/`.

The `metric-addition-reviewer` agent enforces this 7-step checklist.

When a metric ships **rule-based prose** (`reason`, `assessment`, `suggestions`) and you later add an **LLM-generated counterpart** (via `api/insights_generator.py`), keep the rule-based path live as the deterministic fallback for users without `AZURE_AI_ENDPOINT` set. Frontend prefers `insight.translations[locale]` and falls back to top-level English fields, then to the rule-based component when no `AiInsight` row exists.

## How to Add a New Data Source

1. `sync/{source}_sync.py` — follow `garmin_sync.py` pattern.
2. SQLAlchemy model in `db/models.py`; upsert logic in `db/sync_writer.py`.
3. Register provider in `analysis/providers/` and `data_loader.py::load_all_data()`.
4. Add synthetic fixtures in `data/sample/{source}/`.
5. Update `scripts/generate_sample_data.py`.

## Running

Always use the project venv at `.venv/` for Python commands.

```bash
# First time: clone with submodules so plugins/praxys/ is populated
# (the plugin is its own public repo, dddtc2005/praxys-coach-plugin)
git clone --recurse-submodules https://github.com/dddtc2005/praxys.git
cd praxys
# (already cloned without --recurse-submodules? run: git submodule update --init)

# First time: copy .env and generate encryption key
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(f'PRAXYS_LOCAL_ENCRYPTION_KEY={Fernet.generate_key().decode()}')" >> .env

# Activate venv: .venv\Scripts\activate (Windows) or source .venv/bin/activate (Unix)
pip install -r requirements.txt

# API server
python -m uvicorn api.main:app --reload

# Frontend dev server (separate terminal)
cd web && npm install && npm run dev

# Tests / lint
python -m pytest tests/ -v
cd web && npx eslint src/
```

On a fresh DB the first registered user becomes admin (no invitation code). Subsequent users need invitation codes, generated from the Admin page. `PRAXYS_ADMIN_EMAIL` always gets admin rights.

### WeChat Mini Program auth

The `/api/auth/wechat/*` endpoints (`login`, `link-with-password`, `register`) let a WeChat Mini Program authenticate against the same backend. WeChat-only users get a synthetic sentinel in `users.email` (`wechat:<openid>`) since FastAPI-Users requires a non-null email; users who supply an email+password on register can also log in via the normal web flow. Invitation-code rules are shared with the web register route via `api/invitations.py`.

Required env vars (set only if you're running a mini program):
- `WECHAT_MINIAPP_APPID` — from `mp.weixin.qq.com` → 开发 → 开发设置
- `WECHAT_MINIAPP_SECRET` — same page; rotate like any secret
- If unset, the endpoints return 503 `WECHAT_NOT_CONFIGURED` (the rest of the app is unaffected)

### Publishing the mini program

Don't tell the user to "open WeChat DevTools and click 上传." Uploads are CI-driven via `.github/workflows/miniapp-publish.yml` (uses `miniprogram-ci`). Versioning is **CalVer, per-component tags** — `miniapp-YYYY.MM.MICRO` (e.g. `miniapp-2026.04.1`) for releases; `main` pushes auto-publish to robot 5 with a synthetic `YYYY.MM.DD.<run>-<sha>` version. The release line is robot 1; robots are independent slots in 版本管理. Promoting 开发版 → 体验版 and 提交审核 / 发布 stay manual in mp.weixin.qq.com (no first-party openapi for them). Full design rationale: `docs/dev/miniapp-cicd-research.md`.

Secrets (already configured): `WECHAT_MINIAPP_APPID`, `WECHAT_MINIAPP_UPLOAD_KEY`. IP whitelist is intentionally off — the upload key is the security boundary.

#### How to release the mini program

When the user says "release the miniapp" / "ship miniapp 2026.05.1" / "cut a new mini program release":

**Prereq.** Sync local refs with GitHub so tag lookups and `git log` work. Run from the repo root:

```bash
git fetch --tags origin && git checkout main && git pull --ff-only
```

**1. Pick the next CalVer tag.** Find the latest existing miniapp release:

```bash
gh release list --limit 20 --json tagName --jq '.[].tagName' | grep '^miniapp-' | head -3
```

Choose `miniapp-YYYY.MM.MICRO` for the current month (UTC). Reset `MICRO` to `1` at the start of each new month; otherwise increment from the most recent tag in the same month. If nothing matches, this is the first release — use `miniapp-YYYY.MM.1`.

**2. Draft release notes from git log.** Diff from the previous miniapp tag (or, on the very first release, walk the whole miniapp-relevant history):

```bash
prev=$(gh release list --limit 20 --json tagName --jq '.[].tagName | select(startswith("miniapp-"))' | head -1)
if [ -n "$prev" ]; then
  git log "$prev..HEAD" --oneline -- miniapp/ web/src/locales/ web/src/types/api.ts
else
  git log --oneline -- miniapp/ web/src/locales/ web/src/types/api.ts | head -200
fi
```

Group the shortlog into 3–5 user-readable bullet themes (features, fixes, polish). Write the curated notes to a file — using `--notes-file` instead of inline `--notes "..."` avoids the heredoc-indentation pitfall when this snippet is nested under a list item:

```bash
$EDITOR /tmp/miniapp-release-notes.md   # or write it from the chat directly
```

**3. Create the release.** Atomically creates the tag, pushes it, and triggers `miniapp-publish.yml`:

```bash
gh release create miniapp-2026.05.1 --target main \
  --title "Miniapp 2026.05.1" \
  --notes-file /tmp/miniapp-release-notes.md
```

**4. Watch the publish workflow** until it goes green. There's a brief queue delay between `gh release create` returning and the workflow run appearing — short sleep handles it:

```bash
sleep 5
gh run watch "$(gh run list --workflow=miniapp-publish.yml --limit 1 --json databaseId --jq '.[0].databaseId')" --exit-status
```

The job summary shows version + robot 1 + a `desc` like `release 2026.05.1 (abc1234)` — note the `miniapp-` prefix is stripped from the tag in the desc string.

**5. Hand off to the user for the manual WeChat steps.** Tell them exactly what to click, in order:

- mp.weixin.qq.com → 版本管理 → robot 1 row → **选为体验版**
- Scan the QR with WeChat to smoke-test against the previous 体验版
- **提交审核** (1–7 day human review)
- Once approved: **发布**

These last three steps have no first-party API for self-hosted operators — they must be clicked.

Don't try to bump `miniapp/package.json` `version` as part of the release — tags are the source of truth, the package.json field is unused by the publish workflow. Don't open a PR for a release; releases are tag-driven, not commit-driven.

## Documentation

See `docs/dev/contributing.md` for which files to update with code changes. Key dev docs:
- `docs/brand/index.html` — Praxys brand guideline (interactive, authoritative visual source)
- `docs/dev/architecture.md` — detailed architecture
- `docs/dev/api-reference.md` — API endpoint contracts
- `docs/dev/design-system.md` — design system implementation rules (translates brand guide → `web/src/`)
- `docs/dev/gotchas.md` — domain-specific traps
- `plugins/praxys/skills/*/SKILL.md` — skill instructions

## Claude Code Automations

Automations live in `.claude/` and are committed so every contributor using Claude Code sees the same behavior. See `.claude/settings.json` for hooks (block edits to secrets; run pytest on Python changes; run ESLint on web TS changes), `.claude/agents/` for subagents (`science-reviewer`, `metric-addition-reviewer`, `api-contract-reviewer` — all read-only), and `.claude/skills/` for dev-workflow skills.

## AI Skills

8 skills in `plugins/praxys/skills/` (submodule from public [`dddtc2005/praxys-coach-plugin`](https://github.com/dddtc2005/praxys-coach-plugin)) expose training features via the Praxys plugin (MCP server + skills):

| Skill | Purpose |
|-------|---------|
| `setup` | Connections, training base, thresholds, goals |
| `science` | Browse / select training science theories |
| `sync-data` | Trigger Garmin / Stryd / Oura sync |
| `daily-brief` | Today's signal, recovery, upcoming workouts |
| `training-review` | Multi-week diagnosis + suggestions |
| `training-plan` | Generate 4-week AI training plan |
| `race-forecast` | Race prediction + goal feasibility |
| `add-metric` | Scaffold a new metric end-to-end |

The MCP server (`plugins/praxys/mcp-server/server.py`) runs in dual mode — local (direct DB) or remote (HTTP + JWT via `PRAXYS_URL`).

AI features are always optional; the app works fully without `AZURE_AI_ENDPOINT` (the post-sync LLM insight runner falls back to rule-based prose, and the training-context builder still feeds skill-side AI plan generation). When set, Azure OpenAI powers the bilingual insight generator (`api/insights_generator.py`), plan validator, and the `AiPlanProvider` that loads `data/ai/training_plan.csv`.
