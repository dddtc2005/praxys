# PC-side baseline setup (Windows + Git Bash + Docker Desktop)

Everything the baseline runner needs to work from your Windows machine.

## Prerequisites

- **Docker Desktop** — already installed. Verify: `docker --version` → should print 20.x or newer.
- **Git Bash** — comes with Git for Windows. All scripts assume bash syntax.
- **Python 3.10+** — for the analyzer. Verify: `python --version` → 3.10+.

No WSL2 required; Docker Desktop's Windows containers (or the embedded Linux VM in WSL2 backend, either works) and Git Bash are enough.

## One-time: pull the sitespeed.io image

First run is slow (~500 MB image pull); later runs reuse the cache.

```bash
docker pull sitespeedio/sitespeed.io:latest
```

## First sanity run

From the repo root, run against the production landing page, anonymous (S4), desktop only, single iteration:

```bash
bash scripts/sitespeed_runner.sh --probe cn-pc --scenario s4 --device desktop --runs 1
```

Expected: a new directory under `docs/perf-baselines/<YYYY-MM-DD>-<short-sha>/s4-cn-pc-desktop/` populated with sitespeed.io output (index.html, pages/, data/browsertime.har, data/browsertime.json).

If Chrome crashes inside the container, confirm `--shm-size=1g` is present in the runner (it is by default).

## Running a real anchor baseline

Full Tier-1 matrix from your PC = S4 × desktop + mobile, 3 runs each (the default):

```bash
bash scripts/sitespeed_runner.sh --probe cn-pc --scenario s4 --device both
```

Takes ~3–6 minutes end-to-end. Output path is printed at the end.

## Parsing the output

Once runs complete, feed the baseline directory to the analyzer:

```bash
python scripts/analyze_baseline.py --baseline-dir docs/perf-baselines/<YYYY-MM-DD>-<sha>
```

Prints markdown table sections per scenario. Paste them into that baseline's `README.md` (copy from `docs/perf-baselines/TEMPLATE.md` first).

## Troubleshooting

**`docker: command not found`** → Docker Desktop isn't running, or your Git Bash shell pre-dated its install. Restart the shell after starting Docker Desktop.

**`Error response from daemon: mount denied`** → Docker Desktop → Settings → Resources → File sharing — add your repo's drive (e.g., `D:\`).

**`MSYS_NO_PATHCONV` not recognized / paths look mangled** → The runner already sets it where needed. If you see `/D:/Dev/...` inside error messages, it's Git Bash converting a Unix-looking path to a Windows one — usually harmless but tells you the shell is trying to help too hard.

**Slow first run, fast subsequent runs** → First run boots Chrome inside the container, caches plugins, and downloads any missing npm deps. Later runs reuse the container layer cache. Normal.

**`fonts.googleapis.com` row missing in analyzer output** → That means the Google Fonts request either never fired (good news, maybe it's blocked before the request leaves your machine) or the HAR entry timed out. Check the browsertime.har manually; the cell's `Font CSS TTFB` shows `timeout` in that case.

## Login-required scenarios (S1, S2, S3)

The runner now supports the three logged-in scenarios in addition to S4:
- **S1** — Cold Today via login
- **S2** — Cold Training via login
- **S3** — Warm Today repeat visit (after login + warm-up)

```bash
# All four scenarios on both form factors
bash scripts/sitespeed_runner.sh --probe cn-pc --scenario all --device both

# Just the login-required ones
bash scripts/sitespeed_runner.sh --probe cn-pc --scenario s1,s2,s3 --device both
```

Login defaults to the public demo account (`demo@trainsight.dev` / `demo`, the same defaults `Landing.tsx`'s "Try the demo" button uses). Override via env vars if you need a different account:

```bash
PRAXYS_PERF_USER=other@example.com PRAXYS_PERF_PASSWORD=secret \
  bash scripts/sitespeed_runner.sh --probe cn-pc --scenario s1 --device desktop
```

`PRAXYS_PERF_BASE_URL` overrides the host (defaults to `https://www.praxys.run`); useful for testing against a staging deploy.

## What this PR doesn't yet cover

- **S1 / S2 / S3 in CI (ACI workflow)** — the login scripts work locally; pushing them through the ACI workflow needs the YAML deployment file pattern (the current `--command-line` argv parser shreds compound args). Tracked separately.
