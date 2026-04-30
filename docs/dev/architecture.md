# Architecture

## System Overview

```
Garmin/Stryd/Oura APIs
        |
   sync/*.py          Fetch + normalize → DB rows
        |
   db/                SQLAlchemy ORM + SQLite
   ├── models.py         9 models (User, Activity, etc.)
   ├── session.py        Engine + session management + auto-migration
   ├── crypto.py         Envelope encryption (Key Vault / Fernet)
   └── sync_writer.py    Upsert helpers for sync scripts
        |
   analysis/          Pure computation layer
   ├── data_loader.py    DB + CSV loading, cross-source merging
   ├── metrics.py        All metric functions (pure, no I/O)
   ├── zones.py          Zone boundary calculation
   ├── config.py         User config (DB-backed with file fallback)
   ├── science.py        Theory loading from YAML
   └── providers/        Platform-specific data adapters
        |
   api/               FastAPI application
   ├── main.py           App + lifespan (init_db, scheduler)
   ├── auth.py           JWT token validation middleware
   ├── users.py          FastAPI-Users integration
   ├── deps.py           Data layer (get_dashboard_data())
   ├── ai.py             AI context builder + plan validation
   └── routes/           Thin endpoint handlers
        |
   ┌────┴────────────┐
   web/    plugins/praxys/
   React   MCP server (12 tools,
   SPA     local + remote modes)
```

## Key Design Decisions

### Single Computation Entry Point

`api/deps.py:get_dashboard_data()` is the sole entry point for all computed data. It:
1. Loads config and data from the database (per-user)
2. Resolves thresholds (auto-detect + manual overrides)
3. Loads active science theories
4. Computes all metrics (fitness/fatigue, diagnosis, predictions, recovery)

Both the API routes and MCP plugin tools call this function. This ensures web and CLI always show identical data.

### Pure Metric Functions

All functions in `analysis/metrics.py` are pure — they take data in, return results out, with no I/O or side effects. This makes them testable and composable. I/O is handled by `data_loader.py` (reading) and `api/deps.py` (orchestration).

### SQLite Database

Training data is stored in a SQLite database (`DATA_DIR/trainsight.db`) via SQLAlchemy ORM. This replaced the earlier flat-CSV approach to support multi-user deployments:
- Per-user data isolation via `user_id` foreign keys on all data tables
- Encrypted credential storage (platform passwords never stored in plaintext)
- Atomic writes via transactions
- `data/sample/` CSVs still exist for seeding and testing

### Database Layer

**Engine:** SQLAlchemy ORM with both sync (for pandas data loading) and async (for FastAPI-Users) sessions. The database file lives at `DATA_DIR/trainsight.db` (configurable via the `DATA_DIR` environment variable, defaults to `data/`).

**Models** (defined in `db/models.py`):

| Model | Table | Purpose |
|-------|-------|---------|
| `User` | `users` | FastAPI-Users user model (email, hashed_password, is_superuser) |
| `Invitation` | `invitations` | One-time registration codes (code, created_by, used_by, is_active) |
| `UserConfig` | `user_config` | Per-user settings (training_base, thresholds, zones, goal, science, preferences) |
| `UserConnection` | `user_connections` | Platform credentials per user (encrypted_credentials, wrapped_dek, status) |
| `Activity` | `activities` | Merged activity data from all sources (distance, duration, power, HR, pace, load scores) |
| `ActivitySplit` | `activity_splits` | Per-interval split data within activities (split-level power, pace, HR) |
| `RecoveryData` | `recovery_data` | Sleep and readiness data (HRV, sleep score, resting HR, body temp) |
| `FitnessData` | `fitness_data` | Per-metric fitness tracking (VO2max, CP estimate, LTHR, max HR) |
| `TrainingPlan` | `training_plans` | Planned workouts from Stryd or AI (targets, description, meta) |

**Session management** (`db/session.py`):
- `init_db()` creates both sync and async engines, runs `create_all()`, then applies lightweight schema migrations
- `get_db()` is a FastAPI dependency yielding sync sessions
- `get_async_db()` yields async sessions for FastAPI-Users

### Auto-Migration

`init_db()` in `db/session.py` includes a lightweight migration system that runs on every startup. After `create_all()` (which only creates new tables), it inspects existing tables for missing columns and runs `ALTER TABLE ... ADD COLUMN` statements. This avoids needing a full Alembic setup for simple schema additions. New columns are registered in the `_migrations` list inside `init_db()`.

### Authentication

**JWT via FastAPI-Users.** All data endpoints require a valid `Authorization: Bearer <token>` header. Tokens are issued by `POST /api/auth/login` (FastAPI-Users auth backend) and validated by `api/auth.py:get_current_user_id()`.

**Registration flow:**
1. First user on a fresh database becomes admin automatically (no invitation code needed)
2. A user whose email matches `PRAXYS_ADMIN_EMAIL` env var registers without an invitation and becomes admin
3. All other users must provide a valid one-time invitation code (generated by an admin via `POST /api/admin/invitations`)

The custom registration endpoint (`api/routes/register.py`) enforces these rules and delegates password hashing to FastAPI-Users' `UserManager`.

### Credential Encryption

Platform credentials (Garmin/Stryd passwords, Oura tokens) are stored encrypted using envelope encryption (`db/crypto.py`):

1. A fresh **Data Encryption Key (DEK)** is generated per credential (Fernet)
2. The DEK encrypts the credential JSON
3. The DEK itself is wrapped by a **master key**:
   - **Production:** RSA key in Azure Key Vault (`KEY_VAULT_URL` + `KEY_VAULT_KEY_NAME` env vars)
   - **Development:** Local Fernet key (`PRAXYS_LOCAL_ENCRYPTION_KEY` env var)
4. Both `encrypted_credentials` and `wrapped_dek` are stored as binary columns on `UserConnection`

If `KEY_VAULT_URL` is set, the `CredentialVault` initializes an Azure `CryptographyClient`. Otherwise, it falls back to local Fernet encryption. If neither is configured, it generates an ephemeral key and logs a warning (credentials will not survive restarts).

### Admin System

Admin endpoints (`api/routes/admin.py`) are gated by `is_superuser=True` on the authenticated user. Capabilities:

- **User management:** List all users, delete a user (cascades all their data), toggle admin role
- **Invitation codes:** Generate (`TS-XXXX-XXXX` format), list with usage status, revoke
- Self-modification safeguards: admins cannot delete themselves or change their own role
- **Demo accounts:** Read-only accounts that mirror an admin's data (see below)

### Demo Accounts

Demo accounts let admins share a live, read-only view of their dashboard with others.

**Data model:** Two columns on `User`: `is_demo: bool` and `demo_of: FK → users.id`. When `is_demo` is true, all data queries resolve to `demo_of` (the admin's user_id) instead of the demo user's own id.

**Auth dependencies (`api/auth.py`):**
- `get_current_user_id` — resolves the authenticated user (unchanged)
- `get_data_user_id` — returns `demo_of` for demo users, own `user_id` for normal users. Used on all READ endpoints.
- `require_write_access` — raises 403 for demo users. Used on all WRITE endpoints.

**How it works:**
1. Admin creates a demo account via `POST /api/admin/demo-accounts` (email + password)
2. The demo user is created with `is_demo=True, demo_of=<admin's user_id>`
3. Demo user logs in normally (JWT auth) but all data reads are scoped to the admin's data
4. All write operations (settings, sync, plans, connections) return 403
5. Frontend shows a persistent amber banner: "Live demo with real training data — read-only mode"
6. Settings page is visually dimmed with pointer-events disabled

**Key design decisions:**
- No data duplication — demo users see live data that updates when the admin syncs
- Each admin's demo accounts only see that admin's data (supports multiple admins)
- Server-side enforcement — even direct API calls get 403, not just UI hiding

### Pluggable Science Framework

Training theories (load models, zone frameworks, prediction methods, recovery protocols) are YAML files in `data/science/`. The user selects one theory per pillar in their config. This means:
- Metrics adapt to the selected theory (zone boundaries, time constants, etc.)
- New theories can be added by creating a YAML file — no code changes
- Citations link back to the original research papers

### Multi-Source Data Merging

Activities can come from Garmin, Stryd, or Coros. `data_loader.py` merges them:
- Primary source set via `config.preferences.activities`
- Secondary sources enrich with additional columns (e.g., Stryd adds power to Garmin activities)
- Matching uses date + timestamp proximity (handles timezone differences)

### LLM-backed Insights

The post-sync hook (`api/insights_runner.py`) runs three bilingual insight generators (`daily_brief`, `training_review`, `race_forecast`) after every sync, gated by:

- **Content-addressable cache.** Each insight type has a SHA-256 fingerprint (`analysis/insight_hash.py`) of the inputs that drive it (recovery state, sessions, CP trend, goal, etc.). The user's selected science pillars are folded in, so swapping load model from Banister to Seiler invalidates the hash and regenerates on next sync. If the hash matches the previously stored `AiInsight.meta["dataset_hash"]`, generation is skipped.
- **Per-user daily cap.** `PRAXYS_INSIGHT_DAILY_CAP` (default 30) bounds LLM calls per user per UTC day. When the cap is exhausted the runner short-circuits and existing rows persist.
- **Graceful fallback.** When `AZURE_AI_ENDPOINT` is unset (or the openai/azure-identity SDKs are missing), `api.llm.get_client()` returns `None`, generators return `None`, and the rule-based prose in `analysis/metrics.py` continues to render unchanged. Sync never fails because of insight generation — both hook sites swallow exceptions.

**Bilingual generation (issue #103).** A single LLM call returns `{"en": {...}, "zh": {...}}`. The English block populates the existing top-level columns (`headline`, `summary`, `findings`, `recommendations`); the zh block lands in the new additive `translations` JSON column. Categorical enums (finding `type`) stay as English keys and are translated client-side via `web/src/lib/display-labels.ts`. The frontend reads `insight.translations[locale]` with English fallback. `LocaleContext.setLocale` invalidates React Query so cached locale-sensitive payloads (science labels, AI insights) refetch immediately on switch.

**Hook points.** `api/routes/sync.py::_run_sync()` (the API-triggered path) and `db/sync_scheduler.py::_sync_connection()` (background scheduler) both call `run_insights_for_user(user_id, db, counts)` after `db.commit()`, wrapped in try/except.

**Auth.** `api/llm.py::get_client()` uses `DefaultAzureCredential` + `get_bearer_token_provider` — same scaffolding as `scripts/translate_missing.py`. No API key path. Reasoning deployment configured via `PRAXYS_INSIGHT_MODEL`; translation deployment via `TRANSLATE_MODEL`.

**Mini program.** The miniapp's `utils/insights.ts` exposes `localizedInsight()` and `fetchInsight()` helpers, and the synced `types/api.ts` carries the `translations` field, but the miniapp does **not** yet render the AI insights card on today / training / goal pages. Tracked as a parity gap; the rule-based prose those pages already render continues to work and remains the deterministic fallback.

### MCP Plugin

The Praxys MCP plugin (`plugins/praxys/mcp-server/server.py`) provides 12 tools for Claude Code and Copilot CLI. It operates in two modes:

**Remote mode** (`PRAXYS_URL` env var set):
- All tool calls proxy to the deployed API via HTTP
- JWT token read from `~/.trainsight/token`
- Used by end users connecting to the cloud deployment

**Local mode** (`PRAXYS_URL` not set):
- Direct Python imports from the project codebase
- Uses the first active user in the local database (or `PRAXYS_USER_ID` override)
- `get_dashboard_data()` called directly, no HTTP overhead
- Used during development

**Tools:**

| Tool | Description |
|------|-------------|
| `get_daily_brief` | Today's training signal, recovery, upcoming workouts |
| `get_training_review` | Zone distribution, fitness/fatigue, diagnosis, suggestions |
| `get_race_forecast` | Race prediction, CP trend, goal feasibility |
| `get_training_context` | Full context for AI plan generation |
| `get_settings` | Current user settings and display config |
| `update_settings` | Update training base, thresholds, zones, goal |
| `get_connections` | Connected platforms and their status |
| `connect_platform` | Store encrypted credentials for a platform |
| `disconnect_platform` | Remove platform credentials |
| `push_training_plan` | Upload AI-generated plan as CSV |
| `trigger_sync` | Trigger data sync from connected platforms |
| `get_sync_status` | Check sync status for all platforms |

## Module Responsibilities

### db/

Database layer:
- **`models.py`**: 9 SQLAlchemy ORM models (see Database Layer section above)
- **`session.py`**: Engine initialization, `init_db()` with auto-migration, `get_db()`/`get_async_db()` FastAPI dependencies
- **`crypto.py`**: `CredentialVault` class — envelope encryption with Azure Key Vault or local Fernet fallback
- **`sync_writer.py`**: Upsert helpers for writing sync data (activities, splits, recovery, fitness, plans)
- **`csv_import.py`**: One-time migration from flat CSVs to database
- **`sync_scheduler.py`**: Optional background sync scheduler (per-user, periodic)

### sync/

Each sync script (`garmin_sync.py`, `stryd_sync.py`, `oura_sync.py`) is self-contained:
- Authenticates with the platform API
- Fetches new data since last sync (or from `--from-date`)
- Normalizes to the model schema
- Writes to the database via `db/sync_writer.py`

`sync_all.py` orchestrates all three with error isolation per source.

### analysis/

- **`config.py`**: `UserConfig` dataclass, `load_config()`/`save_config()` (file), `load_config_from_db()`/`save_config_to_db()` (DB), platform capabilities, zone defaults
- **`data_loader.py`**: `load_data()` returns a dict of DataFrames: `activities`, `splits`, `recovery`, `fitness`, `plan`
- **`metrics.py`**: ~40 pure functions covering RSS, TRIMP, EWMA, TSB, predictions, diagnosis, recovery analysis
- **`zones.py`**: Computes zone ranges from threshold + boundary fractions
- **`science.py`**: Loads YAML theories, merges with label sets, provides `load_active_science()`
- **`training_base.py`**: Display config per training base (labels, units, abbreviations)
- **`providers/`**: Platform-specific adapters for threshold detection and plan loading

### api/

- **`main.py`**: FastAPI app, lifespan (init_db, optional sync scheduler), CORS (local dev only), route registration
- **`auth.py`**: JWT validation middleware — `get_current_user_id()` extracts user ID from Bearer token
- **`users.py`**: FastAPI-Users integration — auth backend, user manager, transport configuration
- **`deps.py`**: The big orchestrator. `get_dashboard_data()` loads everything, computes everything, returns a dict consumed by all routes.
- **`ai.py`**: `build_training_context()` serializes dashboard data into LLM-optimized JSON. `validate_plan()` checks generated plans.
- **`routes/`**: Each route file is a thin wrapper extracting relevant keys from `get_dashboard_data()`. Includes `register.py` (custom registration with invitation codes) and `admin.py` (user/invitation management).

### web/

React SPA (Vite + TypeScript + Tailwind v4 + shadcn/ui):
- **`pages/`**: 4 pages matching dashboard tabs (Today, Training, Goal, Settings) + Science
- **`components/`**: UI components, one per card/section
- **`hooks/`**: `useApi<T>` for data fetching with loading/error states
- **`types/api.ts`**: TypeScript interfaces matching API response shapes
- **`lib/chart-theme.ts`**: Single source of truth for chart colors

### plugins/praxys/

MCP plugin for Claude Code and Copilot CLI:
- **`mcp-server/server.py`**: 12 tools with dual-mode execution (see MCP Plugin section)
- **`mcp-server/auth.py`**: Token management helpers for remote mode

### .claude/skills/

8 skill directories, each with a `SKILL.md` (instructions for AI tools). Skills that need data have corresponding Python CLI tools in the top-level `scripts/` directory that output JSON to stdout.

## Data Flow Examples

### "What should I do today?"

```
GET /api/today (with Bearer token)
  → get_current_user_id() → JWT validation → user_id
  → get_dashboard_data(user_id, db)
    → load_data() → query activities + recovery + plan from DB
    → _resolve_thresholds() → auto-detect CP from fitness_data
    → load_active_science() → get recovery theory params
    → analyze_recovery() → HRV status (Kiviniemi/Plews)
    → daily_training_signal() → Go/Modify/Rest
  → extract signal + recovery + upcoming + last activity
  → JSON response
```

### "Diagnose my training"

```
GET /api/training (with Bearer token)
  → get_current_user_id() → JWT validation → user_id
  → get_dashboard_data(user_id, db)
    → load_data() → activities + splits from DB
    → diagnose_training(merged, splits, cp_trend, ...)
      → volume analysis (weekly km, trend)
      → consistency check (gaps, session count)
      → interval intensity (split-level, supra-CP sessions)
      → zone distribution (actual vs target from theory)
      → _add_diagnosis_items() → findings + suggestions
  → JSON response
```
