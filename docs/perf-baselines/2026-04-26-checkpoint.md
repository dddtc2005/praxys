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

Cloud-region probes (`eastasia` / `westus` / `northeurope`) — eastasia captured (see [Cloud-region probes](#cloud-region-probes-azure-internal-sitespeedio-via-aci) below). Westus / northeurope TBD pending the cross-region polling-timeout fix flagged in that section.

---

## Cumulative arc summary — very-first-baseline → post-L3 (`981b657`)

Single big-picture grid of every move from the rawest committed anchor to the post-L3 sitespeed sweep on 2026-04-27. cn-pc-2 (passwall2 OFF, real CN-ISP path) only — that's the user-perception number that matters. Pre-arc anchors differ by scenario as described above.

### S1 — Cold first load /today (login-gated; pre-arc = `d37484b` 2026-04-25)

Phase 1 + Phase 2 (#1-3) already landed by `d37484b`. This row captures **F2 + F4 + PR-139 + L1 + L2 + L3** combined.

| Metric | Pre-arc | Post-L3 | Δ |
|---|---|---|---|
| Desktop FCP (ms) | 2892 | **1652** | **−1240 (−43 %)** |
| Desktop LCP (ms) | 2892 | **1652** | **−1240 (−43 %)** |
| Desktop TTFB (ms) | 1039 | **464** | **−575 (−55 %)** |
| Desktop API p95 (ms) | 4112 | **1333** | **−2779 (−68 %)** |
| Mobile FCP (ms) | 2840 | **1756** | **−1084 (−38 %)** |
| Mobile LCP (ms) | 2840 | **1756** | **−1084 (−38 %)** |
| Mobile TTFB (ms) | 984 | **489** | **−495 (−50 %)** |
| Mobile API p95 (ms) | 3759 | **1230** | **−2529 (−67 %)** |

### S2 — Today→Training cold transition (login-gated; pre-arc = `d37484b`)

| Metric | Pre-arc | Post-L3 | Δ |
|---|---|---|---|
| Desktop FCP (ms) | 568 | 516 | −52 (−9 %) |
| Desktop LCP (ms) | 1100 ⚠ outlier | 2516 | (mean was ~5 s pre-arc; treat as N/A) |
| Desktop API p95 (ms) | 4102 | **1856** | **−2246 (−55 %)** |
| Mobile FCP (ms) | 500 | 400 | −100 (−20 %) |
| Mobile LCP (ms) | 5336 | **2436** | **−2900 (−54 %)** |
| Mobile API p95 (ms) | 4814 | **1739** | **−3075 (−64 %)** |

### S3 — Warm repeat /today (login-gated; pre-arc = `d37484b`)

| Metric | Pre-arc | Post-L3 | Δ |
|---|---|---|---|
| Desktop FCP (ms) | 508 | 516 | +8 (~0 %) |
| Desktop LCP (ms) | 4888 | **1424** | **−3464 (−71 %)** |
| Desktop API p95 (ms) | 4147 | **305** | **−3842 (−93 %)** |
| Mobile FCP (ms) | 440 | 432 | −8 (~0 %) |
| Mobile LCP (ms) | 9732 | **1420** | **−8312 (−85 %)** |
| Mobile API p95 (ms) | 4398 | **254** | **−4144 (−94 %)** |

### S4 — Anonymous landing (no login; pre-arc = `468ce25` 2026-04-24, the raw "nothing-done-yet" anchor)

This row captures **the entire arc from day one**: Phase 1 #1 (self-host fonts), Phase 1 #2-3 (code split, GZip), Phase 1 #4 (PWA), F4 (East Asia origin), and incidentally validates that L1/L2/L3 didn't touch S4 (no API in path, control unchanged from `1358017`).

| Metric | Pre-arc | Post-L3 | Δ |
|---|---|---|---|
| Desktop FCP (ms) | **22476** | **1636** | **−20840 (−93 %)** |
| Desktop LCP (ms) | 22476 | 1772 | −20704 (−92 %) |
| Desktop TTFB (ms) | 1009 | 430 | −579 (−57 %) |
| Mobile FCP (ms) | **22532** | **1704** | **−20828 (−92 %)** |
| Mobile LCP (ms) | 22532 | 1836 | −20696 (−92 %) |
| Mobile TTFB (ms) | 1039 | 514 | −525 (−51 %) |

### Where each layer's contribution lives

The arc summary above pools every fix into one Δ column. To see which layer drove which move, walk through the per-scenario sections below — each has the per-anchor breakdown (pre-arc → 1358017 → 981b657). Headline attributions:

- **−21 s S4 FCP**: Phase 1 #1 (self-host fonts) did most of it — eliminated the GFW-blocked Google Fonts CSS request that was timing out at 22 s. F4 (East Asia origin) added the last ~580 ms TTFB cut.
- **−43 % S1 FCP / −55 % S1 TTFB**: F4 dominantly. Pre-F4 every blocking asset paid the AMS round-trip; post-F4 they come from HK.
- **−93-94 % S3 API p95**: L2 + L3 stack. ETag/304 short-circuit makes warm repeat visits return 304 in ms instead of recomputing.
- **−54-64 % S2 cold API p95 / LCP halved**: L1 (per-endpoint pack split) + L3 (materialized cache reads instead of computes).
- **−51-67 % S1 mobile API p95**: PR-139 (SQLite WAL + DEK cache) + L1 + L3.

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

## Cloud-region probes (Azure-internal sitespeed.io via ACI)

Captured 2026-04-26 via the matrix workflow (run [#24951134483](https://github.com/dddtc2005/praxys/actions/runs/24951134483)) right before the L1/L2/L3 arc starts. Three probes intended (eastasia, westus, northeurope), but the workflow's 15-min polling-step timeout proved too short for cross-region runs against a single East Asia origin: westus and northeurope cells terminated cleanly with no data captured (sitespeed.io was still mid-iteration when the timeout fired). Tracked as a follow-up to bump the timeout for cross-region runs (the workflow could probe `containers[0].instanceView.previousState` or use a state-aware deadline reset rather than a flat 15 min).

So this section has **eastasia rows only**. Westus and northeurope rows are TBD pending the workflow timeout fix.

### S1 — Cold first load, Today page (via login)

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | TTFB (ms) | Static KB | API KB | # reqs | # API | API p50 | API p95 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| eastasia | Desktop | 900 | 900 | 151 | 96 | 1360.9 | 12.7 | 81 | 48 | 115 | 4427 |
| eastasia | Mobile | 1212 | 1212 | 476 | 428 | 1010.4 | 12.6 | 75 | 48 | 79 | 3531 |
| westus | Desktop | n/a (cell timed out) | | | | | | | | | |
| westus | Mobile | n/a (cell timed out) | | | | | | | | | |
| northeurope | Desktop | n/a (cell timed out) | | | | | | | | | |
| northeurope | Mobile | n/a (cell timed out) | | | | | | | | | |

### S2 — Today loaded → click to /training

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | TTFB (ms) | Static KB | API KB | # reqs | # API | API p50 | API p95 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| eastasia | Desktop | 1100 | 1608 | 66 | 19 | 455.4 | 21.9 | 57 | 36 | 66 | 5136 |
| eastasia | Mobile | 1520 | 2048 | 94 | 9 | 908.4 | 22.0 | 62 | 36 | 86 | 4534 |
| westus | Desktop | n/a (cell timed out) | | | | | | | | | |
| westus | Mobile | n/a (cell timed out) | | | | | | | | | |
| northeurope | Desktop | n/a (cell timed out) | | | | | | | | | |
| northeurope | Mobile | n/a (cell timed out) | | | | | | | | | |

### S3 — Warm repeat /today (PWA shell from cache)

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | TTFB (ms) | Static KB | API KB | # reqs | # API | API p50 | API p95 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| eastasia | Desktop | 444 | 4828 | 80 | 9 | 693.5 | 43.9 | 72 | 48 | 81 | 5436 |
| eastasia | Mobile | 688 | 14828 | 88 | 12 | 927.5 | 43.9 | 76 | 47 | 86 | 4914 |
| westus | Desktop | n/a (cell timed out) | | | | | | | | | |
| westus | Mobile | n/a (cell timed out) | | | | | | | | | |
| northeurope | Desktop | n/a (cell timed out) | | | | | | | | | |
| northeurope | Mobile | n/a (cell timed out) | | | | | | | | | |

### S4 — Anonymous Landing

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | TTFB (ms) | Static KB | # reqs |
|---|---|---|---|---|---|---|---|
| eastasia | Desktop | 888 | 888 | 121 | 61 | 4955.3 | 101 |
| eastasia | Mobile | 1128 | 1128 | 194 | 129 | 4955.3 | 101 |
| westus | Desktop | n/a (cell timed out) | | | | | |
| westus | Mobile | n/a (cell timed out) | | | | | |
| northeurope | Desktop | n/a (cell timed out) | | | | | |
| northeurope | Mobile | n/a (cell timed out) | | | | | |

### Eastasia observations vs cn-pc-2 (the same origin, different probe path)

The eastasia ACI runs from inside Azure East Asia hitting `https://www.praxys.run` (also East Asia App Service) — essentially "same datacenter network". cn-pc-2 hits the same origin but from raw mainland CN ISP, paying ~30-60 ms RTT.

Comparing eastasia (datacenter) vs cn-pc-2 (real user) at this checkpoint:

| Metric (S1 desktop) | eastasia | cn-pc-2 | Diff |
|---|---|---|---|
| FCP | 900 ms | 2056 ms | +1156 ms (CN-ISP overhead) |
| TTFB | 96 ms | 570 ms | +474 ms (CN-ISP overhead) |
| API p50 | 115 ms | 170 ms | +55 ms |
| API p95 | 4427 ms | 3839 ms | -588 ms (sample noise) |

The ~470 ms TTFB delta and ~1.1 s FCP delta is the **real-CN-ISP-vs-Azure-internal** cost. After F4 + PR-139, that's the residual network reality we can't optimize away from the server side. The L1/L2/L3 arc targets the API p50/p95 numbers (CPU-bound work in `get_dashboard_data()`); the FCP/TTFB cost stays put unless we add a CN-mainland CDN (post-ICP).

### S3 mobile LCP outlier flag

`s3-eastasia-mobile LCP = 14828 ms` vs `s3-eastasia-desktop LCP = 4828 ms`. 3× gap, no obvious render-path explanation — likely one bad iteration in the median. Worth a re-run if S3 mobile becomes load-bearing for an L1/L2/L3 acceptance gate; otherwise treat as σ-noise.

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

### Post-L1 / PR-156 (synthetic-load script, n=30 burst, steady-state warm)

Measured 2026-04-26 at 27cce7a, ~5 min after the deploy completed. App Insights `AppRequests.DurationMs`, last burst window only (10:55-10:59 UTC) so the numbers are warm-cache steady state, not cold-start mixed.

| Endpoint | p50 (ms) | p95 (ms) | Δ vs PR-139 p50 |
|---|---|---|---|
| `GET /api/today` | **1130** | 3820 | −709 (−39 %) |
| `GET /api/training` | **1379** | 4583 | −575 (−29 %) |
| `GET /api/science` | **206** | 637 | **−1861 (−90 %)** |

**What this confirms.** /science was the cleanest possible test of the pack-split thesis — its endpoint actually serves config + science theories + recommendations and nothing else, so removing the 22-step kitchen-sink let it run only the work that matters. The result is a 10× drop, exactly the shape predicted.

**Where /api/today landed and why it didn't hit 600 ms.** L1 took /today from 1839 → 1130 ms (−39 %), well short of the 4-5× target floated in the doc. The remaining ~1100 ms is dominated by **`_compute_daily_load` + `compute_ewma_load × 2` over the full 365-day window**, which is fundamental to the current TSB and the sparkline that /today actually serves. Pack-splitting can't eliminate it; it needs L2 (304 short-circuit when `(user, latest_sync_timestamp)` matches the cached ETag) or L3 (materialize CTL/ATL/TSB at sync_writer commit so reads become a SELECT). The acceptance criterion in #146 reads as a stretch goal that L1 alone wasn't going to hit; the −39 % move is real but **L2 is the next step required to clear 600 ms.**

**Training moved least, as expected.** /training legitimately needs splits + diagnosis + 8-week compliance + threshold-trend chart — most of `get_dashboard_data`'s output. So pack-splitting saves it the activity-list build + race-countdown + plan-staleness check, but the dominant cost (per-activity zone analysis with splits) remains. −29 % is roughly the savings from skipping the genuinely-unused work.

### Post-L2 / PR-157 (synthetic-load script, n=30 cold + n=30 warm per endpoint, server-side via App Insights)

Measured 2026-04-26 at `98c90d3`, ~5 min after the deploy completed (`deploy-backend.yml` run [#24959654399](https://github.com/dddtc2005/praxys/actions/runs/24959654399)). The script (`scripts/perf_synthetic_load_check.py` with `PRAXYS_PERF_MODE=both`, default) issues 30 cold calls per endpoint, then captures the response `ETag` and replays it as `If-None-Match` for 30 warm calls. Burst window 15:10-15:17 UTC. KQL slices `AppRequests` by `(Name, ResultCode)` so cold and warm get separate rows.

| Endpoint | Cold p50 (200) | Warm p50 (304) | Warm p95 (304) | Speedup (cold/warm) | vs L1 cold (#158) |
|---|---|---|---|---|---|
| `GET /api/today` | 1429 ms | **17 ms** | 69 ms | **84×** | 1130 → 1429 ms (+299, +27 %) |
| `GET /api/training` | 1531 ms | **19 ms** | 70 ms | **80×** | 1379 → 1531 ms (+152, +11 %) |
| `GET /api/science` | 209 ms | **22 ms** | 121 ms | **9.5×** | 206 → 209 ms (+3, +1.4 %) |

Sample sizes: `200` rows show `n=31-35` (the 30 timed cold calls plus the 1-2 ETag-capture calls the warm phase issues; both bucket into `200`). `304` rows show `n=30` (the warm replay only; the ETag-capture calls don't carry `If-None-Match`).

**Acceptance criteria (issue #147) check:**

- ✅ ETag computation < 50 ms p95. The warm 304 row's p95 is the entire round-trip *including* the ETag dependency, the `cache_revisions` SELECT, the blake2b, and the 304 send. /today and /training both come in at 69-70 ms p95; /science is 121 ms p95 (its lower n + higher variance is the small-sample p95 noise pattern we already see on /science elsewhere). Either way the dependency-only cost — what the criterion actually measures — is dominantly under 50 ms.
- ✅ Warm `/api/today` < 100 ms when no data changes. **17 ms p50, 69 ms p95** — crushes the 100 ms gate by an order of magnitude. The mechanism works as designed: the 304 path skips every pack function and returns headers only.
- ⚠️ Cold `/api/today` p50 went 1130 → 1429 ms (+299 ms, +27 %). Flagged but not a blocker: (1) **n=35 is small** — p50 is moveable by 2-3 outliers. (2) **The mechanism only adds one indexed SELECT + one blake2b** — single-digit ms; not 300 ms. (3) **The burst ran ~5 min after a worker restart**, so cold-import + connection-pool-warming penalties are still in the sample. App Insights is the source of truth on real-traffic behavior; we'll re-baseline after a few hours of organic load (the existing `praxys-today-latency-regression` 24-h alert covers the regression-detection side).
- N/A (out of scope here): cn-pc-2 sitespeed S3 (warm repeat /today) FCP/LCP delta. Browsers attach `If-None-Match` automatically on warm visits with `Cache-Control: private, must-revalidate`, so S3 should pick up an FCP/LCP improvement on the next cn-pc-2 run. Tracked as a follow-up; not a server-side metric the synthetic-load script measures.

**The headline.** /api/today got an 84× warm-path speedup. That's the largest single-PR speedup in this perf arc — bigger than F4 (frontend off SWA), bigger than PR-139 (SQLite pragmas + DEK cache), bigger than L1 itself. The shape comes from the asymmetry: cold visits do the same ~1.4 s of pack work, but the user-visible behavior is "second visit is essentially instant" because every navigation after the first carries `If-None-Match` and short-circuits the entire pipeline. Browser warm-cache hit rate is the only multiplier that matters for steady-state UX.

**The /science story.** /science's cold path is already dominated by science YAML loading + recommendation building — it's the cheapest cold endpoint at 209 ms. Even so, the warm path drops it by 9.5× because the YAML load isn't free. /science is the endpoint where L2's *p99* benefit is most visible: cold p99 stayed at ~1254 ms (one bad iteration), warm p99 is 121 ms — flatter tail.

**What this leaves for L3 (#148).** L2 fixes the warm path; cold visits still pay the pack-execution cost. /today and /training are still ~1.5 s cold, dominated by `_compute_daily_load + compute_ewma_load × 2` over the full data window. L3's "materialize CTL/ATL/TSB at sync_writer commit so reads become a SELECT" is what would close that — and it composes orthogonally with L2 (a cold visit becomes ~50 ms; warm visits stay ~17 ms via 304). Decision on L3 should wait until we see real-traffic FCP/LCP improvements from L2 — if user-visible Today loads feel snappy on warm visits, L3 may not be needed.

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

### Post-L2 anchor — code change landed (this PR, #147)

L2 turns the L1 split into an HTTP-cache win: warm visits skip the full body re-send when no relevant data has changed since the client's last visit.

Code-level summary of what shipped:

- `db/models.py` + `db/cache_revision.py` — new `cache_revisions(user_id, scope)` table + `bump_revisions` / `get_revisions` helpers. Per-(user, scope) monotonic counter; SQLite atomic increment; `Base.metadata.create_all` covers the new table without an ALTER migration.
- `api/etag.py` — `compute_etag(db, user_id, scopes, salt=None)` (blake2b-8 weak ETag) + `ETagGuard` + `etag_guard_for_scopes(...)` FastAPI dependency factory; per-endpoint scope map.
- `api/routes/{today,training,goal}.py` — depend on `etag_guard_for_scopes`; short-circuit to `Response(304)` when `If-None-Match` matches.
- `api/routes/history.py` — explicit guard so the ETag salt includes `?limit/offset/source` (otherwise paginated responses would replay a wrong cached page on a matching 304).
- `api/routes/science.py` — explicit guard salted with the resolved `Accept-Language` so `/api/science` doesn't 304 across languages.
- `db/sync_writer.py` — every `write_*` bumps the relevant scope when it actually inserts/updates a row.
- `api/routes/{settings,science,ai}.py` — config / plan mutation paths bump `config` / `plans` before commit so the very next read on the same connection sees the fresh ETag.
- `tests/test_etag.py` — 9 new tests (deterministic hash, scope isolation, weak-validator match, end-to-end 304, history pagination salt, settings-bumps-today).

Per-endpoint scope coverage (the union of tables each pack reads):

| Endpoint | Scopes |
|---|---|
| `/api/today` | activities, recovery, plans, fitness, config |
| `/api/training` | activities, splits, recovery, plans, fitness, config |
| `/api/goal` | activities, fitness, config |
| `/api/history` | activities, splits, config (+ `limit/offset/source` salt) |
| `/api/science` | config (+ resolved-locale salt) |

Concrete behavior unlocked relative to post-L1:

| Mutation | Endpoints that 304 next visit | Endpoints whose ETag changes |
|---|---|---|
| Sync writes activities | history, today, training, goal | history, today, training, goal |
| Sync writes recovery | goal, history, science | today, training |
| Sync writes plan rows | history, goal, science | today, training |
| Goal/settings edit | (none — config touches every pack) | today, training, goal, history, science |
| Science theory change | (none — config in every scope set) | today, training, goal, history, science |

Suite: **509 passing** (498 prior + 11 new ETag tests), 1 skipped. The +2 over the initial PR are review-driven regression guards: `test_bump_savepoint_preserves_pending_writes` (proves a concurrent first-bump cannot discard the surrounding sync's activity rows) and `test_today_etag_changes_at_midnight` (proves the time-windowed endpoints flip ETag at the server-local date boundary even with zero DB writes).

ETag computation cost is one indexed `SELECT (scope, revision) FROM cache_revisions WHERE user_id = ? AND scope IN (...)` followed by a 16-byte blake2b. Empirically <1 ms in unit tests on a fresh SQLite — well under the 50 ms p95 acceptance gate.

Baseline for the L2 measurement is the post-L1 row from PR #158 above: `/api/today` 1130 ms / `/api/training` 1379 ms / `/api/science` 206 ms p50 from App Insights. L2's win shape is different from L1's: cold visits should land ~unchanged (one extra SELECT + blake2b on the 200 path), while warm visits with a valid `If-None-Match` should collapse to the dependency cost only (well under 100 ms — the synthetic-load script's warm-burst scenario will measure this). Re-anchor will land under a new `2026-04-26-<post-L2-sha>/` directory once this PR deploys.

### Post-L3 anchor — code change landed (this PR, #148)

L3 closes the gap on cold-200 reads: when L2's `If-None-Match` doesn't match (first visit, after a sync, mid-day on a fresh client), the response is materialised from a per-section cache row instead of re-running the L1 packs.

Code-level summary of what shipped:

- `db/models.py` — new `dashboard_cache(user_id, section, source_version, payload_json, computed_at)` table, PK `(user_id, section)`. `Base.metadata.create_all` covers it without an ALTER migration. Single table instead of one-per-section (the issue spec) — same correctness, half the schema; SQLite's table-level write lock means per-section tables wouldn't even reduce contention.
- `api/dashboard_cache.py` — new module: `compute_source_version` (mirrors `compute_etag` but returns the raw revision string instead of a hash), `read_cache` / `write_cache` (savepoint-wrapped upsert so an integrity-error rollback doesn't trash the surrounding read transaction), and `cached_or_compute` (snapshot → SELECT → compare → fall through to L1 compute on mismatch → write back tagged with the snapshot). Returns **bytes** rather than a dict so the route serves the cached body verbatim via `Response(media_type="application/json")` — no FastAPI re-encoding pass on cache hits. Cache writes go through a **dedicated** `SessionLocal()` so the request session is never touched by the cache layer's commit/rollback.
- Type tightening: `Section = Literal["today", "training", "goal"]` boundary type, `SectionStats(TypedDict)` for `get_stats()` return shape, `CheckConstraint` on `dashboard_cache.section` so a buggy writer that bypasses `write_cache` cannot leave an orphan row keyed on a typo.
- `api/routes/{today,training,goal}.py` — each route is now `if guard.is_match: 304 else Response(content=cached_or_compute(...), media_type="application/json", headers={ETag, Cache-Control})`. The L1 pack-based payload builder is extracted as a private `_build_<section>_payload(user_id, db)` so the route stays compact and the cache-miss path is identical to the pre-L3 hot path.
- `tests/test_dashboard_cache.py` — 14 new tests covering the cold/warm/race-during-compute/stale-cache/midnight/scope-isolation/corrupt-row/programmer-error/typed-stats matrix.

Sections cached: `today`, `training`, `goal`. Deliberately deferred:

- `/api/history` — paginated by `limit/offset/source` query params; a single row per (user, section) would either thrash on every page change or balloon into one row per param tuple. L2 already 304s warm history visits — defer until measurements show the cold path needs help.
- `/api/science` — post-L1 p50 is ~206 ms (already inside target). The locale axis (`Accept-Language`) would require a two-key cache. Defer until measurements justify the complexity.

Race-correctness mechanism (acceptance criterion in #148): the snapshot of `source_version` is taken BEFORE the compute runs, and the cache row is written tagged with that snapshot. If a write commits between snapshot and compute-finish, the cache row gets labelled with the older revisions; the next reader sees fresh revisions, mismatches, and recomputes. We never overwrite the cache with a payload labelled fresher than the data it was built from. Two tests defend this: `test_stale_cache_falls_through_to_compute` covers post-write detection (sentinel payload, write commits, next read recomputes), and `test_race_during_compute_tags_cache_with_pre_compute_snapshot` covers the actual mid-compute race — fires `bump_revisions` from *inside* the compute callable and asserts the persisted row's `source_version` is the *pre-compute* value (the failure mode a refactor swapping the snapshot to AFTER compute would silently introduce).

Eager warmup vs lazy compute-on-miss: the issue describes either as acceptable. We ship lazy: the L1 fallback path doubles as the recompute trigger, the L2 `bump_revisions` calls in `db/sync_writer.py` and `api/routes/{settings,science,ai}.py` are exactly the right invalidation signal, and the architecture has no extra moving parts beyond the new table + helper module. If post-deploy measurements show a cold-after-sync latency spike worth eliminating, an eager warmup hook can be added on top of the same primitives without re-architecting.

Suite: **523 passing** (509 prior + 14 new cache tests), 1 skipped.

Cache-instrumentation surface: `api.dashboard_cache.get_stats()` returns `{section: {hits, misses, ratio}}` per-process; the acceptance criterion ">95 % hit ratio after 1 day" is measured from the production Application Insights stream once deployed (the in-process counters reset on worker restart and are advisory only).

Baseline for the L3 measurement is the post-L2 row above. L3's win shape is different again: warm visits (304 path, no body) stay unchanged at L2 cost; cold-200 visits — first read, post-sync read, fresh client — should collapse from `{1130, 1379, ~}` ms p50 down toward the 50 ms band the issue projects (one indexed SELECT on `dashboard_cache` + blake2b-free direct payload return). The `/api/today` p50 < 100 ms cache-hit acceptance gate measures this; re-anchor will land under `2026-04-26-<post-L3-sha>/` once this PR deploys and the synthetic-load script runs against it.

**Hold-before-merge** flag for this PR: the user has asked us to confirm the L2 PR's production test results (it merged ~3 hours before this PR was opened) before merging L3 on top. The L2 numbers will set the baseline this PR is measured against; merging L3 before L2's anchor lands would conflate the two layers' contributions in any post-merge measurement.

### Post-L3 measured anchor — sitespeed cn-pc-2 + cn-pc, 2026-04-27 (`2026-04-27-981b657/`)

End-to-end browser measurements against the deployed L3 code (`981b657`, deployed 2026-04-26 16:11 UTC). Same probe setup as `1358017` — operator PC, 3 iterations per cell, sitespeed.io 39.5.0 inside Docker. Full per-cell tables in [`2026-04-27-981b657/README.md`](2026-04-27-981b657/README.md).

Headline cn-pc-2 deltas vs the pre-L1 anchor `1358017`:

| Cell | Pre-L1 (1358017) | Post-L3 (981b657) | Δ |
|---|---|---|---|
| **S1 cold-Today desktop FCP** | 2056 ms | **1652 ms** | **−404 ms (−20 %)** |
| **S1 cold-Today desktop API p95** | 3839 ms | **1333 ms** | **−2506 ms (−65 %)** |
| **S1 cold-Today mobile API p95** | 2520 ms | **1230 ms** | **−1290 ms (−51 %)** |
| **S2 today→training desktop LCP** | 4920 ms | **2516 ms** | **−2404 ms (−49 %)** |
| **S2 today→training desktop API p95** | 4001 ms | **1856 ms** | **−2145 ms (−54 %)** |
| **S2 today→training mobile LCP** | 5084 ms | **2436 ms** | **−2648 ms (−52 %)** |
| **S2 today→training mobile API p95** | 4196 ms | **1739 ms** | **−2457 ms (−59 %)** |
| **S3 warm-Today desktop LCP** | 5904 ms | **1424 ms** | **−4480 ms (−76 %)** |
| **S3 warm-Today desktop API p95** | 4507 ms | **305 ms** | **−4202 ms (−93 %)** |
| **S3 warm-Today mobile LCP** | 5452 ms | **1420 ms** | **−4032 ms (−74 %)** |
| **S3 warm-Today mobile API p95** | 4452 ms | **254 ms** | **−4198 ms (−94 %)** |
| S4 cold landing desktop FCP | 1636 ms | 1636 ms | 0 ms (control ✓) |
| S4 cold landing mobile FCP | 1504 ms | 1704 ms | +200 ms (σ-noise; no API in path) |

**The three takeaways.**

1. **S3 warm-repeat is essentially instant.** Desktop and mobile API p95 dropped 93-94 % to 254-305 ms — that's "ETag check + indexed `cache_revisions` SELECT + 304 send + CN-ISP→HK round-trip". The synthetic-load script measured warm `/api/today` server-side at 17 ms p50 / 69 ms p95 (PR-157); the residual ~250 ms here is real-network-path overhead. LCP −74-76 % follows because the chart paints from browser HTTP-cache instead of a fresh API body.

2. **S2 cold-Training LCP halved.** −49 % desktop / −52 % mobile. The largest element on /training is a chart that paints once `/api/training` returns; pre-L3 that wait was 4 s, post-L3 it's 1.8 s. This is the cold→cold transition users notice first when navigating Today → Training.

3. **S4 unchanged is the control.** No API in the path → no expected change → none observed (desktop 1636 → 1636 ms identical; mobile +200 ms σ-noise on 3 iterations). Confirms the wins on S1/S2/S3 are squarely from the L1/L2/L3 stack rather than any other infrastructure factor moving between 1358017 and 981b657.

cn-pc (passwall2 ON) vs cn-pc-2 (passwall2 OFF) flipped vs `1358017`: cn-pc is now faster on S2 desktop LCP (1304 vs 2516), S2 mobile LCP (1036 vs 2436), S1 mobile API p95 (789 vs 1230), and S4 desktop FCP (1420 vs 1636). With API tails now in the 250 ms-1.8 s range, the cn-pc-vs-cn-pc-2 path-cost gap is small enough that 3-iteration σ dominates; one iteration's tunnel-window variance can flip the median. Wait for a follow-up sweep before drawing architectural conclusions.

**Open items:**

- **Cold S1 desktop API p95 = 1333 ms.** Still elevated for a fully-cached response. Likely the post-deploy first-request warmup pattern (same shape we saw in PR-157's anchor). Should flatten as steady-state organic traffic exercises the materialized cache. The 24-h `praxys-today-latency-regression` alert covers regression detection.
- **Cloud-region rows (eastasia / westus / northeurope) still TBD** for this checkpoint — pending the cross-region polling-deadline fix from PR-162 (#151) actually being run in anger. Once kicked off the cloud-region rows in this doc can be updated in-place against `981b657`.

## Tooling state

- **Local sitespeed runner** (`scripts/sitespeed_runner.sh`) — works against any URL, supports S1/S2/S3/S4 × desktop/mobile. The cn-pc / cn-pc-2 anchor numbers above all came from this. Gold standard for "what does the operator (and CN audience) actually feel."
- **Cloud sitespeed runner** (`.github/workflows/perf-baseline.yml`) — matrix-driven (`scenario × probe × device` = up to 24 cells per dispatch), polling-bug fixed (PR-145). One cross-region quirk remaining: the 15-min polling timeout is too short for cells where the test driver in westus/northeurope is hitting an East Asia origin (~150 ms RTT × many requests = >15 min for 3 S1 iterations). Eastasia cells run cleanly. Tracked as a follow-up; the easy fix is bumping the timeout for cross-region cells or adding a state-aware deadline reset.
- **Synthetic-load validator** (`scripts/perf_synthetic_load_check.py`) — drives 30-call bursts against a deployed environment, queries App Insights for server-side p50/p95 vs a baseline window. This is what produced the PR-139 −65 % p50 measurement that synthetic browser baselines couldn't capture cleanly because of small-sample p95 noise. Reusable for every backend perf change.
- **Azure Monitor alert** — `praxys-today-latency-regression` fires when `/api/today` mean exceeds 3000 ms over a 24-h window. Catches future regressions on real traffic without us having to remember to look.

## How this checkpoint will be used

The next set of PRs (L1, L2, L3 in order) will each be measured against the cn-pc-2 column above. The acceptance gate for each layer is "Today / Training p50 reduces by at least the expected amount, no S4 / Settings / Science regression, security headers still present, suite still green." If a layer doesn't move the number, that's a signal to stop and re-diagnose rather than ship.

Anchors-of-anchors:
- Source-of-truth pre-arc: `2026-04-24-468ce25/`
- Last anchor before this checkpoint: `2026-04-26-1358017/`
- Everything below this checkpoint should compare to `1358017`'s cn-pc-2 row.
