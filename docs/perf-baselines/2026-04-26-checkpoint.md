# Perf checkpoint — 2026-04-26

A snapshot of where Praxys' user-perceived performance stands after the recent four-fix arc (Phase-1 #1 self-host fonts, PWA precache, PR-139 backend pragmas + DEK cache, F4 frontend co-location). This is the **"before" reference** for the next round of work — the L1/L2/L3 backend-call optimizations targeted at Today / Training cold load.

Numerical sources for every claim below are the committed baselines in `docs/perf-baselines/`. This file is just the consolidated narrative.

## What's been fixed so far

| Phase | What | Anchor showing the gain |
|---|---|---|
| Phase 1 #1 | Self-hosted fonts (eliminated Google Fonts blocking on raw CN ISP) | `2026-04-25-667dcc2/` — S4 cn-pc-2 desktop FCP **22476 ms → 2892 ms** (−87 %) |
| Phase 2 #4 (F2) | Folded `/api/plan/stryd-status` into `/api/plan` (one fewer round-trip on Training cold load) | `2026-04-25-d37484b/` set the S1/S2/S3 anchor right before this |
| PR-139 | SQLite WAL pragmas + 20 MB page cache + per-DEK unwrap LRU | `2026-04-25-c73e4a1-backend-perf/` — synthetic-load script measured `/api/today` p50 **5194 ms → 1839 ms** (−65 %) |
| PR-141/142 (F4) | Frontend off SWA-Amsterdam onto App Service East Asia (`praxys-frontend`); apex `praxys.run` lives | `2026-04-26-1358017/` — see headline table below |

## Headline numbers — `cn-pc-2` (passwall2 OFF, raw mainland CN ISP)

This is the row that matters for friends in mainland CN without VPN — the population the recent work was designed to serve.

| Scenario | Metric | Pre-arc (`2026-04-24-468ce25` or `d37484b`) | Now (`1358017`) | Δ |
|---|---|---|---|---|
| **S1 cold-Today desktop** | FCP | 2892 ms | **2056 ms** | −29 % |
| | TTFB | 1039 ms | **570 ms** | −45 % |
| | API p95 | 4112 ms | 3839 ms | −7 % (small sample) |
| **S1 cold-Today mobile** | FCP | 2840 ms | **1680 ms** | −41 % |
| | TTFB | 984 ms | **479 ms** | −51 % |
| | API p95 | 3759 ms | **2520 ms** | −33 % |
| **S2 Today→Training mobile** | LCP | 5336 ms | 5084 ms | −5 % |
| | API p95 | 4814 ms | 4196 ms | −13 % |
| **S3 warm-Today mobile** | LCP | 9732 ms | **5452 ms** | −44 % |
| **S4 cold landing desktop** | FCP | 22476 ms (raw) → 2892 ms (post-Phase-1 #1) | **1636 ms** | −93 % overall, −43 % vs post-Phase-1 |
| **S4 cold landing mobile** | FCP | 22532 ms (raw) → 2788 ms (post-Phase-1 #1) | **1504 ms** | −93 % overall, −46 % vs post-Phase-1 |

### Pre-PR-139 production median (App Insights, real traffic)

| Endpoint | p50 | p95 |
|---|---|---|
| `GET /api/today` | 5194 ms | 11887 ms |
| `GET /api/training` | 4127 ms | 15938 ms |
| `GET /api/science` | 4404 ms | 15549 ms |
| `GET /api/health` | 8 ms | 47 ms |
| `GET /api/settings` | 218 ms | 1098 ms |

### Post-PR-139 synthetic-load median

| Endpoint | p50 | p95 |
|---|---|---|
| `GET /api/today` | **1839 ms** | 3998 ms |
| `GET /api/training` | **1954 ms** | 4391 ms |
| `GET /api/science` | **2067 ms** | 6566 ms |

### Architectural inversion confirmed

Pre-F4: `cn-pc` (passwall2 ON) was always faster than `cn-pc-2` because passwall2 bypassed the GFW-throttled CN→AMS path that SWA-Amsterdam forced on us.

Post-F4: `cn-pc` (passwall2 ON) is *consistently slower* than `cn-pc-2` on Praxys traffic — direct CN-ISP→HK is a shorter route than CN-ISP→overseas-tunnel→HK now that the origin lives in East Asia. Most visible: S4 desktop FCP `cn-pc` 3788 ms vs `cn-pc-2` 1636 ms.

**Friends in mainland CN without VPN now get the best Praxys experience.** That's the right outcome for the audience.

## What's still slow (and where we go next)

The user's current subjective feel (verbatim, lightly paraphrased):

- Landing (`praxys.run` / `www.praxys.run`): fast cold + warm. Done.
- **Today + Training: slow on cold load — data and charts take many seconds; nav bar is quick.**
- Settings, Science: feel fast.
- Warm Today/Training: better, still not snappy.

Code-read (without instrumentation) found the smoking gun: **five endpoints (`/api/today`, `/api/training`, `/api/goal`, `/api/history`, `/api/science`) all call the same kitchen-sink `get_dashboard_data()` function**, which runs ~22 distinct top-level computations on every request, then each endpoint returns ~15-40 % of the result. The other 60-85 % of work is wasted. The four production endpoints clustering near the same 1.8-2 s p50 (post-PR-139) is the data-side fingerprint of this — they're literally doing the same work.

This is what the next three optimization layers target. Each is a separate piece of work with its own measurement gate before moving on:

| Layer | Issue | Mechanism | Expected Today p50 after |
|---|---|---|---|
| **L1** | (TBD — open after PR-145 lands) | Refactor `get_dashboard_data` into per-endpoint slim functions; routes call only what they need | ~400 ms (4-5× drop) |
| **L2** | (TBD) | ETag/304 keyed on `(user, latest_sync_timestamp)` — saves bandwidth on warm visits | minimal compute change; cuts the JSON-body re-send cost |
| **L3** | (TBD) | Materialize per-section caches at sync_writer commit; reads become SELECTs | ~50 ms (≈ instant) |

**L1 is required before L2 and L3 make sense** — without splitting the kitchen-sink, neither caching strategy has a sane invalidation surface. Once L1 lands, L2 is additive and L3 stays in the toolbox until the warm-visit speed of L1 stops feeling adequate.

## Tooling state

- **Local sitespeed runner** (`scripts/sitespeed_runner.sh`) — works against any URL, supports S1/S2/S3/S4 × desktop/mobile. The cn-pc-2 anchor numbers above all came from this. Gold standard for "what does the operator (and CN audience) actually feel."
- **Cloud sitespeed runner** (`.github/workflows/perf-baseline.yml`) — currently being rewritten in PR-145: matrix-driven (`scenario × probe × device` = up to 24 cells per dispatch), polling-bug fixed (was hanging cross-region runs by relying on an unreliable state field). Once PR-145 lands, we have reliable Azure-internal probes for eastasia/westus/northeurope to triangulate audience experience without needing the operator's PC.
- **Synthetic-load validator** (`scripts/perf_synthetic_load_check.py`) — drives 30-call bursts against a deployed environment, queries App Insights for server-side p50/p95 vs a baseline window. This is what produced the PR-139 −65 % p50 measurement that synthetic browser baselines couldn't capture cleanly because of small-sample p95 noise. Reusable for every backend perf change.
- **Azure Monitor alert** — `praxys-today-latency-regression` fires when `/api/today` mean exceeds 3000 ms over a 24-h window. Catches future regressions on real traffic without us having to remember to look.

## How this checkpoint will be used

The next set of PRs (L1, L2, L3 in order) will each be measured against the numbers in this file. The acceptance gate for each layer is "Today / Training p50 reduces by at least the expected amount, no S4 / Settings / Science regression, security headers still present, suite still green." If a layer doesn't move the number, that's a signal to stop and re-diagnose rather than ship.

Anchors-of-anchors:
- Source-of-truth pre-arc: `2026-04-24-468ce25/`
- Last anchor before this checkpoint: `2026-04-26-1358017/`
- Everything below this checkpoint should compare to `1358017`'s cn-pc-2 row.
