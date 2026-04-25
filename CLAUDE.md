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
| `miniapp/` | WeChat Mini Program (Taro 4 + React) | `src/pages/` (login, today, training, goal, settings), `src/lib/` (`api-client.ts` Taro.request wrapper, `auth.ts` WeChat login flow, `format.ts` copied from web), `src/hooks/useApi.ts` (no react-query — mini program size budget), `src/types/api.ts` copied from web. Build: `npm run build:weapp` → `dist/` loaded by WeChat DevTools |
| `plugins/praxys/` | Praxys plugin | `skills/` (8 SKILL.md), `mcp-server/` (local + remote MCP) |
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

## How to Add a New Data Source

1. `sync/{source}_sync.py` — follow `garmin_sync.py` pattern.
2. SQLAlchemy model in `db/models.py`; upsert logic in `db/sync_writer.py`.
3. Register provider in `analysis/providers/` and `data_loader.py::load_all_data()`.
4. Add synthetic fixtures in `data/sample/{source}/`.
5. Update `scripts/generate_sample_data.py`.

## Running

Always use the project venv at `.venv/` for Python commands.

```bash
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

8 skills in `plugins/praxys/skills/` expose training features via the Praxys plugin (MCP server + skills):

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

AI features are always optional; the app works fully without `ANTHROPIC_API_KEY`. When present, AI powers the training-context builder (`api/ai.py`), plan validator, and the `AiPlanProvider` that loads `data/ai/training_plan.csv`.
