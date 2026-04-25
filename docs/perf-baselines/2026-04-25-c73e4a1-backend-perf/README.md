# Backend perf validation: 2026-04-25 — `c73e4a1` (PR-139)

**Purpose:** validate that the SQLite WAL pragmas + per-DEK unwrap cache
shipped in PR-139 actually moved server-side latency on the live App
Service — without waiting for organic traffic (~3 `/api/today` calls/day
is too sparse for stable percentiles).

**Method:** synthetic burst from PC against the App Service origin
(`trainsight-app.azurewebsites.net`, bypassing the SWA proxy on
`www.praxys.run` which doesn't forward POST). 30 sequential requests per
endpoint, 200ms apart, signed in as the read-only demo account (which
proxies reads to the admin's data via `users.demo_of`, so the queries
hit the same SQLite tables and row counts a real user would). After the
burst, a 2-minute wait for App Insights ingestion, then KQL.

The deploy completed at **12:07 UTC**. The synthetic burst ran
**12:22:52–12:27:42 UTC** — well clear of the deploy window.

Reproduce: `python scripts/perf_synthetic_load_check.py`

## Server-side latency (App Insights `AppRequests.DurationMs`)

| Endpoint | Pre p50 | **Post p50** | Δ p50 | Pre p95 | **Post p95** | Δ p95 |
|---|---|---|---|---|---|---|
| `GET /api/today` | 5194 ms | **1839 ms** | **−65 %** | 11887 ms | **3998 ms** | **−66 %** |
| `GET /api/training` | 4127 ms | **1954 ms** | **−53 %** | 15938 ms | **4391 ms** | **−72 %** |
| `GET /api/science` | 4404 ms | **2067 ms** | **−53 %** | 15549 ms | **6566 ms** | **−58 %** |

- Pre = real production traffic, last 7 days before the deploy
  (n = 3-21 per endpoint, low confidence on the tails but the medians
  are credible).
- Post = synthetic burst, n = 30 per endpoint.

## Key Vault unwrap_key cliff (`AppDependencies`)

5-minute bins straddling the deploy boundary at 12:07 UTC:

| 5-min bin (UTC) | unwrap_key calls |
|---|---|
| 11:35 | 4 |
| 11:45 | 4 |
| 11:55 | 1 |
| 12:00 | 4 |
| 12:05 | 3 |
| 12:15 | 4  ← first post-deploy sync tick, cache cold-fill |
| 12:20+ | **0** (no rows emitted = bin had no calls) |

Pre-deploy steady-state ~3-4 calls per 5-min bin from the sync scheduler
decrypting platform credentials each tick. Post-deploy the first tick at
12:15 populates the cache (4 calls — one per credential), then 0 calls
for the rest of the observation window. Exactly the cliff the cache was
designed to produce.

## Client-side timings (sanity check)

From PC via passwall2 → App Service East Asia, includes network RTT:

| Endpoint | n | p50 | p95 | mean |
|---|---|---|---|---|
| `/api/today` | 30 | 2578 ms | 4267 ms | 2877 ms |
| `/api/training` | 30 | 2547 ms | 4289 ms | 2788 ms |
| `/api/science` | 30 | 2680 ms | 7269 ms | 3414 ms |

Client p50 sits ~600-700 ms above server p50, which matches a typical
HK round-trip (cold TLS adds more on the first call). Plausible.

## Interpretation

The forecast in PR-139's description was 30-60 % p50 drop. We landed at
53-65 % across the slow trio, with even sharper p95 drops (58-72 %). The
unwrap_key cliff is binary and clean — no ambiguity that the cache works.

This is enough evidence to call backend perf "good for now" at the
B1 / SQLite-on-/home tier and move on to F4 (frontend off SWA-Amsterdam).
A future DB migration to Azure SQL Serverless / Postgres remains the
right move when traffic grows or when we want sub-second p50, but it's
no longer urgent.

## Caveats

- Synthetic burst is sequential, single-client. Real concurrent load on
  B1 (1 worker, 1.75 GB RAM) would saturate differently — both pre and
  post — but that's not our regime today.
- Pre-baseline n is small (3-21 calls per endpoint over 7 days). Medians
  are stable but the published p95s have wide CIs. The post-PR p95
  drops we measured are large enough that they're not in the
  pre-baseline noise.
- The B1 worker had been warm before the burst (kept alive by the
  webtest pinging `/api/health` every 5 min), so this measures the
  warm steady-state, not cold start. That's the regime real users
  experience the great majority of the time.

## Raw artifacts

- `synthetic-burst-output.txt` — script stdout including per-call
  client timings.
- KQL queries are inlined in `scripts/perf_synthetic_load_check.py`.
