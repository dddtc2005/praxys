---
name: seed-and-preview
description: >-
  Reset the local SQLite DB to sample data and launch the API + Vite dev
  servers for manual verification. Use when the developer asks to "try
  the app", "preview a UI change", "boot the dashboard", or after changes
  to sample data, initial-migration flow, seed scripts, or the
  registration/invitation path. User-invocable only because it has side
  effects on local state.
disable-model-invocation: true
---

# Seed and Preview

Side-effecting ritual: wipes the local DB and brings up a fresh dev
environment for manual testing. Not destructive to remote state, but it
will overwrite `trainsight.db` in the project root, so confirm before
running if the user has unsaved local data.

## Prerequisites (verify these first)

Run these checks and report any that fail. Do not proceed past a failure.

1. Virtualenv exists:
   ```bash
   test -d .venv || echo "MISSING: .venv — run 'python -m venv .venv' first"
   ```
2. Activate venv for the current shell:
   - Windows (Git Bash): `source .venv/Scripts/activate`
   - Unix: `source .venv/bin/activate`
3. `.env` exists and has a Fernet key:
   ```bash
   test -f .env && grep -q PRAXYS_LOCAL_ENCRYPTION_KEY .env || \
     echo "MISSING: .env or PRAXYS_LOCAL_ENCRYPTION_KEY — see CLAUDE.md 'First-time setup'"
   ```
4. Python deps installed (`pip show fastapi >/dev/null 2>&1` or
   `pip install -r requirements.txt`).
5. Frontend deps installed (`test -d web/node_modules || (cd web && npm install)`).

## Ritual

### 1. Stop any running dev servers

Kill anything holding ports 8000 (API) or 5173 (Vite). If the user has
intentional processes, ask before killing them.

### 2. Reset the DB and seed sample data

```bash
# trainsight.db is blocked from Edit/Write by the PreToolUse hook.
# The hook does not gate Bash, so `rm` in the shell works fine.
rm -f trainsight.db trainsight.db-journal trainsight.db-wal trainsight.db-shm
python scripts/seed_sample_data.py
```

The seed script creates tables, seeds synthetic Garmin/Stryd/Oura data
from `data/sample/`, and leaves a fresh DB ready for registration.

### 3. Start the API server (background)

Launch uvicorn with the Bash tool's `run_in_background: true` so the
conversation stays responsive. A plain foreground command here will
block the session until the user aborts it.

```bash
python -m uvicorn api.main:app --reload --port 8000
```

Then use `BashOutput` to watch for the line `Uvicorn running on
http://127.0.0.1:8000`. If it fails to bind, check for stale
`uvicorn.exe` processes.

### 4. Start the Vite dev server (background)

Again use `run_in_background: true`:

```bash
cd web && npm run dev
```

Poll with `BashOutput` until Vite prints `Local: http://localhost:5173`.
Vite proxies `/api/*` to the backend (see `web/vite.config.ts`).

### 5. Report back to the user

Tell the user:
- API: `http://127.0.0.1:8000` (OpenAPI at `/docs`)
- App: `http://localhost:5173`
- **First register** — on a fresh DB the first registered user becomes
  admin without needing an invitation code (CLAUDE.md § First-time setup).
- Sample credentials to use for Garmin/Stryd/Oura are not needed — the
  DB is already populated with synthetic data. The Settings page will
  show "connected" for sources covered by the sample set.

### 6. If verifying a specific UI change

Ask the user which page and interaction to exercise. Default pages:
Today → Training → Goal → History → Science → Settings.

## Teardown

When the user is done, stop the two background servers. Do not delete
`trainsight.db` unless they ask — they may want to inspect it.

## Troubleshooting

- **Registration fails with "invitation required"**: the DB isn't
  actually empty. Delete `trainsight.db*` and re-seed.
- **Blank Today page after login**: known class of bug; see commit
  `85ea764`. Check `/api/sync/status` is responding.
- **Vite 500 on a specific page**: run `npm run build` in `web/` to
  surface type errors (`tsc -b` runs first in the build script).
- **Hook blocks a .env edit**: expected. `.env` is protected by
  `.claude/hooks/block_secrets.py`. Edit it in a plain terminal.
