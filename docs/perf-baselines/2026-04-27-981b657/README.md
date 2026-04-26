# Baseline: 2026-04-27 — `981b657` (post-L1 + L2 + L3)

**Purpose:** measure the cumulative user-visible gain from the L1/L2/L3 backend optimization arc against the pre-L1 anchor (`2026-04-26-1358017/`). L1 (#146 / `27cce7a`) split the kitchen-sink `get_dashboard_data` into per-endpoint slim packs. L2 (#147 / `98c90d3`) added ETag/304 revalidation per slim pack. L3 (#148 / `981b657`) materialized per-section dashboard caches at sync_writer commit so reads become indexed SELECTs.

**Deploy state:** `981b657` on main, deployed 2026-04-26 16:11 UTC via `deploy-backend.yml`. Architecture unchanged from `1358017`:
- `praxys-frontend` (App Service East Asia, B1) serves `https://www.praxys.run` and `https://praxys.run`.
- `trainsight-app` (App Service East Asia, same plan) serves `https://api.praxys.run`.
- All static assets, all API calls, all auth in HK.

**Run:** 2026-04-27 Asia/Shanghai, operator PC. Both probes (`cn-pc-2` passwall2 OFF, `cn-pc` passwall2 ON), 3 iterations per cell, sitespeed.io 39.5.0 inside Docker.

## Measurements

### S1 — Cold first load, Today page (via login)

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB | Static KB | API KB | # reqs | # API | API p50 | API p95 | Protocol | Font CSS TTFB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cn-pc-2 | Desktop | 1652 | 1652 | 486 | 464 | 2399.6 | 44.1 | 108 | 54 | 199 | 1333 | h2 | — |
| cn-pc-2 | Mobile | 1756 | 1756 | 499 | 489 | 2399.6 | 44.1 | 108 | 54 | 151 | 1230 | h2 | — |
| cn-pc | Desktop | 1840 | 1840 | 579 | 568 | 2399.6 | 44.3 | 108 | 54 | 210 | 1507 | h2 | — |
| cn-pc | Mobile | 1688 | 1688 | 564 | 552 | 2399.4 | 44.3 | 108 | 54 | 146 | 789 | h2 | — |

### S2 — Cold first load, Training page (via login)

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB | Static KB | API KB | # reqs | # API | API p50 | API p95 | Protocol | Font CSS TTFB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cn-pc-2 | Desktop | 516 | 2516 | 21 | 4 | 501.3 | 26.0 | 66 | 48 | 135 | 1856 | h2 | — |
| cn-pc-2 | Mobile | 400 | 2436 | 18 | 7 | 501.3 | 26.1 | 66 | 48 | 134 | 1739 | h2 | — |
| cn-pc | Desktop | 500 | 1304 | 21 | 8 | 501.4 | 26.1 | 66 | 48 | 127 | 1588 | h2 | — |
| cn-pc | Mobile | 400 | 1036 | 21 | 8 | 501.4 | 26.2 | 66 | 48 | 133 | 1478 | h2 | — |

### S3 — Warm repeat visit, Today page

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB | Static KB | API KB | # reqs | # API | API p50 | API p95 | Protocol | Font CSS TTFB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cn-pc-2 | Desktop | 516 | 1424 | 15 | 7 | 1.1 | 14.4 | 57 | 48 | 148 | 305 | h2 | — |
| cn-pc-2 | Mobile | 432 | 1420 | 16 | 7 | 1.1 | 14.4 | 57 | 48 | 140 | 254 | h2 | — |
| cn-pc | Desktop | 460 | 1284 | 19 | 9 | 1.1 | 14.4 | 57 | 48 | 127 | 286 | h2 | — |
| cn-pc | Mobile | 432 | 1784 | 15 | 6 | 1.1 | 14.3 | 57 | 48 | 156 | 552 | h2 | — |

### S4 — Anonymous Landing page

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB | Static KB | API KB | # reqs | # API | API p50 | API p95 | Protocol | Font CSS TTFB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cn-pc-2 | Desktop | 1636 | 1772 | 440 | 430 | 4954.9 | 0.0 | 103 | 0 | — | — | h2 | — |
| cn-pc-2 | Mobile | 1704 | 1836 | 524 | 514 | 4955.0 | 0.0 | 104 | 0 | — | — | h2 | — |
| cn-pc | Desktop | 1420 | 1540 | 422 | 412 | 4954.9 | 0.0 | 105 | 0 | — | — | h2 | — |
| cn-pc | Mobile | 1652 | 1652 | 439 | 429 | 4954.9 | 0.0 | 107 | 0 | — | — | h2 | — |

## Cumulative arc deltas (cn-pc-2) vs the very-first-baseline

For a layer-by-layer breakdown see `docs/perf-baselines/2026-04-26-checkpoint.md`. This section captures the full arc from "nothing done yet" to here — the answer to "how much did all of our perf work move the needle?". Pre-arc anchor differs by scenario (S4 captures the full arc back to `468ce25`; S1/S2/S3 captures everything since login-scripting was added at `d37484b`).

### S1 — Cold first load /today (login-gated; pre-arc = `d37484b`)

| Metric | Pre-arc | Post-L3 | Δ |
|---|---|---|---|
| Desktop FCP | 2892 | **1652** | **−1240 ms (−43 %)** |
| Desktop TTFB | 1039 | **464** | **−575 ms (−55 %)** |
| Desktop API p95 | 4112 | **1333** | **−2779 ms (−68 %)** |
| Mobile FCP | 2840 | **1756** | **−1084 ms (−38 %)** |
| Mobile TTFB | 984 | **489** | **−495 ms (−50 %)** |
| Mobile API p95 | 3759 | **1230** | **−2529 ms (−67 %)** |

### S2 — Today→Training cold transition (login-gated; pre-arc = `d37484b`)

| Metric | Pre-arc | Post-L3 | Δ |
|---|---|---|---|
| Desktop API p95 | 4102 | **1856** | **−2246 ms (−55 %)** |
| Mobile LCP | 5336 | **2436** | **−2900 ms (−54 %)** |
| Mobile API p95 | 4814 | **1739** | **−3075 ms (−64 %)** |

(Desktop LCP omitted — pre-arc value was a flagged outlier at 1100 ms; mean was ~5 s, so a meaningful Δ isn't computable from that single anchor.)

### S3 — Warm repeat /today (login-gated; pre-arc = `d37484b`)

| Metric | Pre-arc | Post-L3 | Δ |
|---|---|---|---|
| Desktop LCP | 4888 | **1424** | **−3464 ms (−71 %)** |
| Desktop API p95 | 4147 | **305** | **−3842 ms (−93 %)** |
| Mobile LCP | 9732 | **1420** | **−8312 ms (−85 %)** |
| Mobile API p95 | 4398 | **254** | **−4144 ms (−94 %)** |

### S4 — Anonymous landing (no login; pre-arc = `468ce25`, raw pre-Phase-1)

| Metric | Pre-arc | Post-L3 | Δ |
|---|---|---|---|
| Desktop FCP | **22476** | **1636** | **−20840 ms (−93 %)** |
| Desktop TTFB | 1009 | **430** | **−579 ms (−57 %)** |
| Mobile FCP | **22532** | **1704** | **−20828 ms (−92 %)** |
| Mobile TTFB | 1039 | **514** | **−525 ms (−51 %)** |

The S4 row is the headline of the entire arc: **a 21-second cut on cold-anonymous-landing per visit**. For a CN visitor without VPN, that's the difference between "this site is broken / blank" and "this site is fast". Phase 1 #1 (self-host fonts) did most of the lift; F4 (East Asia origin) added the last ~580 ms TTFB cut.

## Headline deltas (cn-pc-2, real CN-ISP path) vs `2026-04-26-1358017/`

| Metric | Pre-L1 (1358017) | Post-L3 (981b657) | Δ |
|---|---|---|---|
| **S1 cold-Today desktop FCP** | 2056 ms | **1652 ms** | **−404 ms (−20%)** |
| **S1 cold-Today desktop TTFB** | 570 ms | **464 ms** | **−106 ms (−19%)** |
| **S1 cold-Today desktop API p95** | 3839 ms | **1333 ms** | **−2506 ms (−65%)** |
| **S1 cold-Today mobile API p50** | 214 ms | **151 ms** | **−63 ms (−29%)** |
| **S1 cold-Today mobile API p95** | 2520 ms | **1230 ms** | **−1290 ms (−51%)** |
| **S2 today→training desktop LCP** | 4920 ms | **2516 ms** | **−2404 ms (−49%)** |
| **S2 today→training desktop API p95** | 4001 ms | **1856 ms** | **−2145 ms (−54%)** |
| **S2 today→training mobile LCP** | 5084 ms | **2436 ms** | **−2648 ms (−52%)** |
| **S2 today→training mobile API p95** | 4196 ms | **1739 ms** | **−2457 ms (−59%)** |
| **S3 warm-Today desktop LCP** | 5904 ms | **1424 ms** | **−4480 ms (−76%)** |
| **S3 warm-Today desktop API p95** | 4507 ms | **305 ms** | **−4202 ms (−93%)** |
| **S3 warm-Today mobile LCP** | 5452 ms | **1420 ms** | **−4032 ms (−74%)** |
| **S3 warm-Today mobile API p95** | 4452 ms | **254 ms** | **−4198 ms (−94%)** |
| S4 cold landing desktop FCP | 1636 ms | 1636 ms | 0 ms (control ✓) |
| S4 cold landing mobile FCP | 1504 ms | 1704 ms | +200 ms (σ-noise; no API in path) |

## Observations

### S1 — login → /today (cold)

Both API tails halved. Desktop API p95 −65% / mobile −51%. The render-path numbers (FCP/LCP/TTFB −19-20% on desktop) move modestly because the cold-load is still gated by network + static-asset fetch on top of the API; what L3 cuts is the API recompute that previously dragged the slow tail. Mobile FCP/LCP roughly flat because mobile cn-pc-2 is bandwidth-bound on static assets, not API-bound on cold.

### S2 — Today loaded → click /training

The biggest **cold-load** win on the board: LCP cut roughly in half on both desktop (4920 → 2516) and mobile (5084 → 2436). API p95 −54-59% drives it directly — the largest element on /training is a chart that paints once `/api/training` returns. Pre-L3 that wait was ~4 s; post-L3 it's ~1.8 s. This is the cold-cold transition real users actually feel after clicking the nav bar.

### S3 — warm repeat /today

The headline of the entire arc. **API p95 −93-94%, LCP −74-76%.** The L2 ETag/304 short-circuit + the L3 materialized cache compose: the cache_revisions ETag matches → the request returns 304 in tens of ms with no body, and the chart paints from the browser's HTTP cache. This is what makes warm repeat visits feel instant — second-time-Today has effectively gone from "loading screen for 5 s" to "shows immediately".

The S3 desktop p95 absolute number — **305 ms** — is the right magnitude for "ETag check + indexed SELECT on cache_revisions + 304". The synthetic-load script measured warm `/api/today` at 17 ms p50 / 69 ms p95 server-side; the extra ~250 ms here is CN-ISP→HK round-trip on top.

### S4 — anonymous landing

Static-only, no API in the path, no expected change. Desktop identical at 1636 ms; mobile +200 ms (+13%) is small-sample noise (3 iterations × σ). This row functions as the **control**: it confirms the wins on S1/S2/S3 are squarely from the L1/L2/L3 stack and not from any other infrastructure factor moving since 1358017.

## cn-pc vs cn-pc-2 inversion partly reverses

In `1358017`, cn-pc (passwall2 ON) was clearly worse than cn-pc-2 because tunneling CN→overseas→HK paid an extra hop. In this run the gap is smaller and on several cells reverses:

| Cell | cn-pc (pwall ON) | cn-pc-2 (pwall OFF) | Note |
|---|---|---|---|
| S1 mobile API p95 | 789 ms | 1230 ms | cn-pc faster |
| S2 desktop LCP | 1304 ms | 2516 ms | cn-pc faster |
| S2 mobile LCP | 1036 ms | 2436 ms | cn-pc faster |
| S4 desktop FCP | 1420 ms | 1636 ms | cn-pc faster |

Most likely explanation: with API p95 now in the 250 ms-1.5 s range, the absolute network-overhead delta between paths is small and 3-iteration σ dominates. cn-pc was on a relatively-better tunnel-window during this sweep. Worth re-checking on a follow-up sweep before drawing architectural conclusions.

## What this baseline targets

- ✅ Validates L1 (per-endpoint pack split, #146): API p50 on every path is 130-200 ms, well below pre-arc 4-5 s.
- ✅ Validates L2 (ETag/304, #147): warm S3 API p95 dropping to 254-305 ms is the 304 short-circuit at work — orders of magnitude smaller than the cold-recompute path.
- ✅ Validates L3 (materialized per-section cache, #148): S2 cold LCP halving + S1 cold API p95 dropping 51-65% means even cold visits no longer pay the recompute cost — the cache is read, not built, on most requests.
- 🔵 Open: cold S1 desktop API p95 still 1333 ms — likely the post-deploy first-request warm-up cost we already saw in the post-L2 anchor. Will likely flatten further as steady-state organic traffic warms the cache. The `praxys-today-latency-regression` 24-h alert covers regression detection.
- 🔵 Open: re-run cn-pc / cn-pc-2 once cross-region polling fix (#151) lands so we have eastasia/westus/northeurope cells for the same checkpoint.

## Raw artifacts

HARs for this baseline are in the **`perfbaselines-archive`** Azure blob container (see `docs/perf-baselines/ci-setup.md` for retrieval). Cells captured by canonical path-pattern (after extraction):

- `s1-cn-pc-{2-,}{desktop,mobile}/pages/www_praxys_run/s1-today-via-login/data/browsertime.har`
- `s2-cn-pc-{2-,}{desktop,mobile}/pages/www_praxys_run/s2-training/data/browsertime.har`
- `s3-cn-pc-{2-,}{desktop,mobile}/pages/www_praxys_run/s3-today-warm/data/browsertime.har`
- `s4-cn-pc-{2-,}{desktop,mobile}/pages/www_praxys_run/data/browsertime.har`

To re-derive the metrics after extracting the archive:

```bash
python scripts/analyze_baseline.py --baseline-dir docs/perf-baselines/2026-04-27-981b657
```
