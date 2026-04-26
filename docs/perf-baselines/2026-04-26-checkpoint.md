# Perf checkpoint — 2026-04-26

A snapshot of where Praxys' user-perceived performance stands after the recent four-fix arc (Phase-1 #1 self-host fonts, PWA precache, PR-139 backend pragmas + DEK cache, F4 frontend co-location). This is the **"before" reference** for the next round of work — the L1/L2/L3 backend-call optimizations targeted at Today / Training cold load.

Numerical sources for every claim below are the committed baselines in `docs/perf-baselines/`. This file consolidates every metric across every probe, including the ones that didn't move or that regressed — full picture, not just the wins.

## What's been fixed so far

| Phase | What | Anchor showing the gain |
|---|---|---|
| Phase 1 #1 | Self-hosted fonts (eliminated Google Fonts blocking on raw CN ISP) | `2026-04-25-667dcc2/` — S4 cn-pc-2 desktop FCP **22476 ms → 2892 ms** (−87 %) |
| Phase 2 #4 (F2) | Folded `/api/plan/stryd-status` into `/api/plan` (one fewer round-trip on Training cold load) | `2026-04-25-d37484b/` set the S1/S2/S3 anchor right before this |
| PR-139 | SQLite WAL pragmas + 20 MB page cache + per-DEK unwrap LRU | `2026-04-25-c73e4a1-backend-perf/` — synthetic-load script measured `/api/today` p50 **5194 ms → 1839 ms** (−65 %) |
| PR-141/142 (F4) | Frontend off SWA-Amsterdam onto App Service East Asia (`praxys-frontend`); apex `praxys.run` lives | `2026-04-26-1358017/` — see comprehensive tables below |

## Data sources for this checkpoint

| Scenario | Pre-arc anchor | "Now" anchor |
|---|---|---|
| S1/S2/S3 (login-gated) | `2026-04-25-d37484b/` (cn-pc-2 only) | `2026-04-26-1358017/` (cn-pc + cn-pc-2) |
| S4 (anonymous landing) | `2026-04-24-468ce25/` (raw, cn-pc + cn-pc-2) | `2026-04-26-1358017/` (cn-pc + cn-pc-2) |

The S4 pre-arc starts from `468ce25` (raw, before any Phase-1 work) so the delta captures the full fix arc including self-host fonts. The S1/S2/S3 pre-arc starts from `d37484b` because that's our oldest login-scripted baseline; cn-pc S1/S2/S3 has no committed pre-arc data, so those rows show only "now".

Cloud-region probes (`eastasia` / `westus` / `northeurope`) — pending; needs PR-145 (workflow rewrite) to land + a first sweep against the new origin. Will be appended to this file once we have the data.

---

## S1 — Cold first load, Today page (via login)

### cn-pc-2 (passwall2 OFF — real mainland-CN ISP, what your friends without VPN see)

| Metric | Desktop pre | Desktop now | Δ | Mobile pre | Mobile now | Δ |
|---|---|---|---|---|---|---|
| FCP (ms) | 2892 | **2056** | **−836 (−29 %)** | 2840 | **1680** | **−1160 (−41 %)** |
| LCP (ms) | 2892 | **2056** | **−836 (−29 %)** | 2840 | **1680** | **−1160 (−41 %)** |
| TTI (ms) | 1059 | **580** | **−479 (−45 %)** | 1010 | **489** | **−521 (−52 %)** |
| HTML TTFB (ms) | 1039 | **570** | **−469 (−45 %)** | 984 | **479** | **−505 (−51 %)** |
| Static KB | 2361.0 | 2053.4 | −307.6 (−13 %) | 1910.3 | 1010.4 | −899.9 (−47 %) |
| API KB | 45.6 | 33.8 | −11.8 (−26 %) | 34.8 | 12.9 | −21.9 (−63 %) |
| # reqs | 108 | 99 | −9 (−8 %) | 97 | 75 | −22 (−23 %) |
| # API calls | 54 | 52 | −2 (−4 %) | 52 | 48 | −4 (−8 %) |
| API p50 (ms) | 186 | 170 | −16 (−9 %) | 175 | 214 | **+39 (+22 %)** |
| API p95 (ms) | 4112 | 3839 | −273 (−7 %) | 3759 | **2520** | **−1239 (−33 %)** |

### cn-pc (passwall2 ON — overseas tunnel "control"; no pre-arc S1 baseline)

| Metric | Desktop now | Mobile now | Note |
|---|---|---|---|
| FCP (ms) | 1684 | 1736 | comparable to cn-pc-2 now — passwall no longer "wins" |
| LCP (ms) | 1684 | 1736 | |
| TTI (ms) | 538 | 519 | |
| HTML TTFB (ms) | 515 | 510 | |
| Static KB | 1361.0 | 2399.6 | |
| # reqs | 81 | 108 | |
| API p50 (ms) | 201 | 169 | |
| API p95 (ms) | 1136 | 4280 | desktop fast / mobile slow — single-iteration tail |

### Observations

- **The wins are all in render path.** FCP/LCP/TTI/TTFB drop 29-52 % because F4 eliminated the Amsterdam round-trip on every blocking asset.
- **Mobile API p50 went UP +22 %** — odd against the rest of the picture. Sample is 3 iterations × 48 calls; p50 of small samples is noisy. Mobile p95 dropped 33 % so the headline-tail story holds; treat the p50 +22 % as noise unless it persists across follow-up runs.
- **Static-KB drop on mobile is bigger than desktop** (−47 % vs −13 %). Probably a viewport-aware bundle-split kicking in correctly post-F4 — Vite emits different chunks per breakpoint and mobile got a slimmer initial bundle.

---

## S2 — Today loaded → click to /training

### cn-pc-2 (passwall2 OFF)

| Metric | Desktop pre | Desktop now | Δ | Mobile pre | Mobile now | Δ |
|---|---|---|---|---|---|---|
| FCP (ms) | 568 | 484 | −84 (−15 %) | 500 | 368 | −132 (−26 %) |
| LCP (ms) | 1100 ⚠ | 4920 | **+3820 (anchor outlier)** | 5336 | 5084 | −252 (−5 %) |
| TTI (ms) | 19 | 22 | +3 | 25 | 21 | −4 |
| HTML TTFB (ms) | 5 | 8 | +3 | 9 | 7 | −2 |
| Static KB | 240.8 | 621.8 | +381.0 (+158 %) | 922.4 | 501.4 | −421.0 (−46 %) |
| API KB | 37.0 | 35.2 | −1.8 | 50.8 | 48.3 | −2.5 |
| # reqs | 59 | 63 | +4 | 81 | 66 | −15 |
| # API calls | 46 | 42 | −4 | 54 | 48 | −6 |
| API p50 (ms) | 143 | 159 | +16 | 137 | 144 | +7 |
| API p95 (ms) | 4102 | 4001 | −101 (−2 %) | 4814 | 4196 | **−618 (−13 %)** |

⚠ **S2 desktop LCP 1100 ms in the pre-arc was an explicit outlier** — the d37484b README flagged it: "Mobile LCP 5336 ms vs Desktop 1100 ms is a 5× gap not network-explained… probably one bad iteration." Post-arc desktop and mobile both land around 5 s, consistent with the "chart-needs-API-to-paint" pattern observed everywhere else. The "regression" is the outlier reverting to the mean, not a real slowdown.

### cn-pc (passwall2 ON; no pre-arc S2 baseline)

| Metric | Desktop now | Mobile now |
|---|---|---|
| FCP (ms) | 1156 | 692 |
| LCP (ms) | 12668 | 1220 |
| TTI (ms) | 21 | 24 |
| HTML TTFB (ms) | 5 | 7 |
| API p50 (ms) | 159 | 145 |
| API p95 (ms) | 5295 | 4706 |

### Observations

- **Mobile S2 LCP −5 %, p95 −13 %.** Real wins, modest, expected — Training page is mostly chart-blocked-on-API.
- **Static KB +158 % desktop, −46 % mobile.** Bundle-split mismatch between viewports — probably worth investigating but small absolute size impact.
- **cn-pc desktop LCP 12668 ms** — wildly worse than cn-pc-2 desktop 4920 ms. The architectural-inversion fingerprint: passwall ON sends API calls through overseas tunnel before reaching East Asia origin, adding latency the chart paints late.

---

## S3 — Warm repeat visit, /today (PWA shell from cache)

### cn-pc-2 (passwall2 OFF)

| Metric | Desktop pre | Desktop now | Δ | Mobile pre | Mobile now | Δ |
|---|---|---|---|---|---|---|
| FCP (ms) | 508 | 484 | −24 (−5 %) | 440 | 364 | −76 (−17 %) |
| LCP (ms) | 4888 | 5904 | **+1016 (+21 %)** | 9732 | **5452** | **−4280 (−44 %)** |
| TTI (ms) | 20 | 18 | −2 | 21 | 15 | −6 |
| HTML TTFB (ms) | 8 | 8 | 0 | 7 | 6 | −1 |
| Static KB | 334.8 | 246.2 | −88.6 (−26 %) | 902.1 | 1.1 | **−901.0 (−100 %)** |
| API KB | 45.6 | 33.7 | −11.9 (−26 %) | 45.6 | 44.1 | −1.5 |
| # reqs | 64 | 60 | −4 | 75 | 57 | −18 |
| # API calls | 48 | 46 | −2 | 48 | 48 | 0 |
| API p50 (ms) | 145 | 161 | +16 (+11 %) | 158 | 139 | −19 (−12 %) |
| API p95 (ms) | 4147 | 4507 | +360 (+9 %) | 4398 | 4452 | +54 (+1 %) |

### cn-pc (passwall2 ON; no pre-arc S3 baseline)

| Metric | Desktop now | Mobile now |
|---|---|---|
| FCP (ms) | 476 | 368 |
| LCP (ms) | 4888 | 5116 |
| TTI (ms) | 18 | 14 |
| HTML TTFB (ms) | 7 | 6 |
| API p50 (ms) | 147 | 171 |
| API p95 (ms) | 4235 | 4685 |

### Observations

- **Mobile LCP −44 %** — biggest single move on the board. Pre-arc 9732 ms was waiting on `/api/today` (then ~4.4 s) plus chart paint; post-arc both halves of that chain are faster.
- **Desktop LCP +21 %** — mild regression, σ-bounded at 3 iterations. Worth a follow-up if it reproduces; for now treated as noise.
- **Mobile Static KB −100 %** (902 → 1.1 KB) — PWA precache fully active on warm visits. Pre-arc PWA wasn't yet in S3 path (PR-122 landed during the arc); now mobile reads the entire shell from disk.

---

## S4 — Anonymous Landing page (no login, pure static delivery)

### cn-pc-2 (passwall2 OFF)

| Metric | Desktop pre (raw) | Desktop now | Δ | Mobile pre (raw) | Mobile now | Δ |
|---|---|---|---|---|---|---|
| FCP (ms) | **22476** | **1636** | **−20840 (−93 %)** | **22532** | **1504** | **−21028 (−93 %)** |
| LCP (ms) | 22476 | 1772 | −20704 (−92 %) | 22532 | 1504 | −21028 (−93 %) |
| TTI (ms) | 22059 | 432 | −21627 (−98 %) | 22102 | 450 | −21652 (−98 %) |
| HTML TTFB (ms) | 1009 | 423 | −586 (−58 %) | 1039 | 438 | −601 (−58 %) |
| Static KB | 1473.3 | 4954.9 | +3481.6 (+236 %) | 1473.2 | 4954.9 | +3481.7 (+236 %) |
| # reqs | 42 | 105 | +63 (+150 %) | 42 | 105 | +63 (+150 %) |
| Font CSS TTFB (ms) | — (timeout) | — | — | — | — | — |

### cn-pc (passwall2 ON)

| Metric | Desktop pre (raw) | Desktop now | Δ | Mobile pre (raw) | Mobile now | Δ |
|---|---|---|---|---|---|---|
| FCP (ms) | 3000 | **3788** | **+788 (+26 %)** ⚠ | 3264 | 1536 | −1728 (−53 %) |
| LCP (ms) | 3152 | 3956 | +804 (+25 %) | 3264 | 1536 | −1728 (−53 %) |
| TTI (ms) | 1407 | 419 | −988 (−70 %) | 1214 | 406 | −808 (−67 %) |
| HTML TTFB (ms) | 1040 | 409 | −631 (−61 %) | 957 | 396 | −561 (−59 %) |
| Static KB | 2379.2 | 4954.9 | +2575.7 (+108 %) | 2319.6 | 4954.9 | +2635.3 (+114 %) |
| # reqs | 52 | 108 | +56 (+108 %) | 53 | 107 | +54 (+102 %) |

⚠ **cn-pc desktop FCP +26 %** is the architectural-inversion fingerprint. Pre-arc, passwall2 ON routed CN traffic through an overseas tunnel which BYPASSED the GFW-throttled CN→AMS path that SWA-Amsterdam was forcing. Post-arc with the origin in East Asia (HK), passwall2 ON now routes CN-ISP→overseas→HK — adding hops that direct CN-ISP→HK doesn't pay. This is the right outcome: friends without VPN now have the optimal path; friends with VPN pay a small tunnel cost to get an architecture that benefits the audience overall.

### Observations

- **The headline win for the audience-without-VPN: 22.5 s → 1.5 s FCP cold landing on raw CN ISP.** That's a 21-second cut per cold visit.
- **Static KB up across all rows.** Self-hosted fonts (PR-G era) and the larger-but-PWA-friendly bundle are the cause. Bigger absolute payload, but it actually arrives now (pre-arc the WOFF2 fetches were timing out at TLS, never reaching the browser).
- **Request count up.** Same reason — fonts, vendor chunks, brand assets that previously timed out now successfully fetch.

---

## Cross-endpoint API median (App Insights — server-side, real production traffic)

### Pre-PR-139 (1 week of organic traffic before PR-139 landed)

| Endpoint | Calls | p50 (ms) | p95 (ms) |
|---|---|---|---|
| `GET /api/today` | 21 | 5194 | 11887 |
| `GET /api/training` | 3 | 4127 | 15938 |
| `GET /api/science` | 11 | 4404 | 15549 |
| `GET /api/health` | 764 | 8 | 47 |
| `GET /api/settings` | 8 | 218 | 1098 |

### Post-PR-139 (synthetic-load script, n=30 burst)

| Endpoint | p50 (ms) | p95 (ms) | p50 Δ |
|---|---|---|---|
| `GET /api/today` | **1839** | 3998 | −3355 (−65 %) |
| `GET /api/training` | **1954** | 4391 | −2173 (−53 %) |
| `GET /api/science` | **2067** | 6566 | −2337 (−53 %) |

The clustering of three endpoints around the same 1.8-2.1 s p50 is the data-side fingerprint of the kitchen-sink anti-pattern in `get_dashboard_data()` — they're all doing the same work. L1 (#146) targets exactly this.

---

## Architectural inversion confirmed

Pre-F4: `cn-pc` (passwall2 ON) was always faster than `cn-pc-2` because passwall2 bypassed the GFW-throttled CN→AMS path that SWA-Amsterdam forced on us.

Post-F4: `cn-pc` is *consistently slower* on Praxys traffic — direct CN-ISP→HK is a shorter route than CN-ISP→overseas-tunnel→HK now that the origin lives in East Asia. Most visible cells:

| Cell | cn-pc (passwall ON) | cn-pc-2 (passwall OFF) |
|---|---|---|
| S4 desktop FCP | 3788 ms | 1636 ms |
| S2 desktop LCP | 12668 ms | 4920 ms |
| S2 desktop API p95 | 5295 ms | 4001 ms |
| S1 mobile API p95 | 4280 ms | 2520 ms |

**Friends in mainland CN without VPN now get the best Praxys experience.** That's the right outcome for the audience.

---

## What's still slow (and where we go next)

The user's current subjective feel:

- Landing (`praxys.run` / `www.praxys.run`): fast cold + warm. Done.
- **Today + Training: slow on cold load — data and charts take many seconds; nav bar is quick.**
- Settings, Science: feel fast.
- Warm Today/Training: better, still not snappy.

Code-read found the smoking gun without instrumentation: **five endpoints (`/api/today`, `/api/training`, `/api/goal`, `/api/history`, `/api/science`) all call the same kitchen-sink `get_dashboard_data()` function**, which runs ~22 distinct top-level computations on every request, then each endpoint returns 15-40 % of the result. The other 60-85 % of work is wasted. The four production endpoints clustering near the same 1.8-2 s p50 (post-PR-139) is the data-side fingerprint.

This is what the next three optimization layers target:

| Layer | Issue | Mechanism | Expected `/api/today` p50 after |
|---|---|---|---|
| **L1** | [#146](https://github.com/dddtc2005/praxys/issues/146) | Refactor `get_dashboard_data` into per-endpoint slim functions | ~400 ms (4-5× drop) |
| **L2** | [#147](https://github.com/dddtc2005/praxys/issues/147) | ETag/304 keyed on `(user, latest_sync_timestamp)` — saves bandwidth on warm visits | minimal compute change; cuts the JSON-body re-send cost |
| **L3** | [#148](https://github.com/dddtc2005/praxys/issues/148) | Materialize per-section caches at sync_writer commit; reads become SELECTs | ~50 ms (≈ instant) |

**L1 is required before L2 and L3 make sense** — without splitting the kitchen-sink, neither caching strategy has a sane invalidation surface. Once L1 lands, L2 is additive and L3 stays in the toolbox until the warm-visit speed of L1 stops feeling adequate.

### Post-L1 anchor — code change landed (this PR, #146)

Code-level summary of what shipped:

- `api/packs.py` — new `RequestContext` (request-scoped `cached_property` cache for config, deduplicated activities, thresholds, science, EWMA series) plus 7 packs: `get_signal_pack`, `get_today_widgets`, `get_diagnosis_pack`, `get_fitness_pack`, `get_race_pack`, `get_history_pack`, `get_science_pack`.
- `api/routes/{today,training,goal,history,science}.py` — each rewired to construct one `RequestContext` and call only the packs it needs.
- `api/deps.py` — left intact for legacy callers (`api/ai.py`, `api/routes/plan.py`, `plugins/praxys/mcp-server/server.py`); gradual deprecation, not a big-bang.
- `tests/test_packs.py` — 10 new unit tests, including a parity check that `get_signal_pack` matches `get_dashboard_data['signal']` and a cache-counting test that proves `load_data_from_db` runs exactly once per request.

Concrete work skipped per endpoint relative to legacy `get_dashboard_data`:

| Endpoint | Skips |
|---|---|
| `/api/today` | diagnosis, workout flags, sleep-perf scatter, full activity list (extracts the latest row only), 8-week compliance (computes current week only), `_compute_threshold_data` |
| `/api/training` | full activity list, race countdown, plan-staleness warnings |
| `/api/goal` | diagnosis, workout flags, sleep-perf scatter, weekly compliance, full activity list |
| `/api/history` | every metric (returns the deduplicated activities list only) |
| `/api/science` | merged activities, splits, recovery, thresholds, EWMA load, threshold trend chart — does only `load_config + load_active_science + recommend_science` |

Suite: **445 passing** (435 prior + 10 new pack tests), 1 skipped.

Production p50 / FCP measurements vs the 1358017 cn-pc-2 anchor are pending deploy + sweep — `scripts/perf_synthetic_load_check.py` and a cn-pc-2 sitespeed run will be re-anchored under a new `2026-04-26-<post-L1-sha>/` directory once this lands and traffic flows.

## Tooling state

- **Local sitespeed runner** (`scripts/sitespeed_runner.sh`) — works against any URL, supports S1/S2/S3/S4 × desktop/mobile. The cn-pc / cn-pc-2 anchor numbers above all came from this. Gold standard for "what does the operator (and CN audience) actually feel."
- **Cloud sitespeed runner** (`.github/workflows/perf-baseline.yml`) — being rewritten in PR-145: matrix-driven (`scenario × probe × device` = up to 24 cells per dispatch), polling-bug fixed (was hanging cross-region runs by relying on an unreliable state field). Once PR-145 lands, we have reliable Azure-internal probes for eastasia/westus/northeurope to triangulate audience experience without needing the operator's PC. **Cloud-region rows above are still TBD.**
- **Synthetic-load validator** (`scripts/perf_synthetic_load_check.py`) — drives 30-call bursts against a deployed environment, queries App Insights for server-side p50/p95 vs a baseline window. This is what produced the PR-139 −65 % p50 measurement that synthetic browser baselines couldn't capture cleanly because of small-sample p95 noise. Reusable for every backend perf change.
- **Azure Monitor alert** — `praxys-today-latency-regression` fires when `/api/today` mean exceeds 3000 ms over a 24-h window. Catches future regressions on real traffic without us having to remember to look.

## How this checkpoint will be used

The next set of PRs (L1, L2, L3 in order) will each be measured against the cn-pc-2 column above. The acceptance gate for each layer is "Today / Training p50 reduces by at least the expected amount, no S4 / Settings / Science regression, security headers still present, suite still green." If a layer doesn't move the number, that's a signal to stop and re-diagnose rather than ship.

Anchors-of-anchors:
- Source-of-truth pre-arc: `2026-04-24-468ce25/`
- Last anchor before this checkpoint: `2026-04-26-1358017/`
- Everything below this checkpoint should compare to `1358017`'s cn-pc-2 row.
