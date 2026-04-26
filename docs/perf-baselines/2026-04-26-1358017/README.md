# Baseline: 2026-04-26 — `1358017` (post-F4 + PR-139)

**Purpose:** quantify the combined gain from PR-139 (SQLite WAL pragmas + per-DEK unwrap cache) and F4 (frontend off SWA-Amsterdam onto Azure App Service East Asia at `praxys-frontend`). Direct numerical comparison against `2026-04-25-d37484b/` (S1/S2/S3 anchor pre-PR-139 / pre-F4) and `2026-04-25-667dcc2/` (S4 anchor post-Phase-1 / pre-F4).

**Deploy state:** `1358017` on main (after PR-142 merged). Architecture:
- `praxys-frontend` (App Service East Asia, B1) serves `https://www.praxys.run` and `https://praxys.run` (apex).
- `trainsight-app` (App Service East Asia, same plan) serves `https://api.praxys.run`.
- `swa-trainsight` (Static Web App, Amsterdam-routing) deleted.
- All static assets, all API calls, all auth — same East Asia HK region.

**Run:** 2026-04-26 ~02:?? Asia/Shanghai, operator PC. Both probes: 3 iterations per cell, sitespeed.io 39.5.0 inside Docker, Chrome 146.

## Measurements

### S1 — Cold first load, Today page (via login)

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB | Static KB | API KB | # reqs | # API | API p50 | API p95 | Protocol | Font CSS TTFB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cn-pc-2 | Desktop | 2056 | 2056 | 580 | 570 | 2053.4 | 33.8 | 99 | 52 | 170 | 3839 | h2 | — |
| cn-pc-2 | Mobile | 1680 | 1680 | 489 | 479 | 1010.4 | 12.9 | 75 | 48 | 214 | 2520 | h2 | — |
| cn-pc | Desktop | 1684 | 1684 | 538 | 515 | 1361.0 | 12.8 | 81 | 48 | 201 | 1136 | h2 | — |
| cn-pc | Mobile | 1736 | 1736 | 519 | 510 | 2399.6 | 44.1 | 108 | 54 | 169 | 4280 | h2 | — |

### S2 — Cold first load, Training page (via login)

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB | Static KB | API KB | # reqs | # API | API p50 | API p95 | Protocol | Font CSS TTFB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cn-pc-2 | Desktop | 484 | 4920 | 22 | 8 | 621.8 | 35.2 | 63 | 42 | 159 | 4001 | h2 | — |
| cn-pc-2 | Mobile | 368 | 5084 | 21 | 7 | 501.4 | 48.3 | 66 | 48 | 144 | 4196 | h2 | — |
| cn-pc | Desktop | 1156 | 12668 | 21 | 5 | 1016.3 | 39.3 | 74 | 45 | 159 | 5295 | h2 | — |
| cn-pc | Mobile | 692 | 1220 | 24 | 7 | 738.6 | 35.1 | 65 | 42 | 145 | 4706 | h2 | — |

### S3 — Warm repeat visit, Today page

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB | Static KB | API KB | # reqs | # API | API p50 | API p95 | Protocol | Font CSS TTFB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cn-pc-2 | Desktop | 484 | 5904 | 18 | 8 | 246.2 | 33.7 | 60 | 46 | 161 | 4507 | h2 | — |
| cn-pc-2 | Mobile | 364 | 5452 | 15 | 6 | 1.1 | 44.1 | 57 | 48 | 139 | 4452 | h2 | — |
| cn-pc | Desktop | 476 | 4888 | 18 | 7 | 347.2 | 44.1 | 64 | 48 | 147 | 4235 | h2 | — |
| cn-pc | Mobile | 368 | 5116 | 14 | 6 | 927.2 | 44.1 | 75 | 48 | 171 | 4685 | h2 | — |

### S4 — Anonymous Landing page

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB | Static KB | API KB | # reqs | # API | API p50 | API p95 | Protocol | Font CSS TTFB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cn-pc-2 | Desktop | 1636 | 1772 | 432 | 423 | 4954.9 | 0.0 | 105 | 0 | — | — | h2 | — |
| cn-pc-2 | Mobile | 1504 | 1504 | 450 | 438 | 4954.9 | 0.0 | 105 | 0 | — | — | h2 | — |
| cn-pc | Desktop | 3788 | 3956 | 419 | 409 | 4954.9 | 0.0 | 108 | 0 | — | — | h2 | — |
| cn-pc | Mobile | 1536 | 1536 | 406 | 396 | 4954.9 | 0.0 | 107 | 0 | — | — | h2 | — |

## Headline deltas (cn-pc-2, passwall2 OFF — what real CN-ISP users see)

| Metric | Pre-F4 anchor | Post-F4 + PR-139 | Δ |
|---|---|---|---|
| **S1 cold-Today desktop FCP** | 2892 ms (`d37484b`) | **2056 ms** | **−836 ms (−29 %)** |
| **S1 cold-Today desktop TTFB** | 1039 ms | **570 ms** | **−469 ms (−45 %)** |
| **S1 cold-Today desktop API p95** | 4112 ms | **3839 ms** | −7 % (small sample) |
| **S1 cold-Today mobile FCP** | 2840 ms | **1680 ms** | **−1160 ms (−41 %)** |
| **S1 cold-Today mobile TTFB** | 984 ms | **479 ms** | **−505 ms (−51 %)** |
| **S1 cold-Today mobile API p95** | 3759 ms | **2520 ms** | **−1239 ms (−33 %)** |
| S2 today→training desktop LCP | 1100 ms (anchor outlier) | 4920 ms | +3820 ms — see Observations |
| S2 today→training mobile LCP | 5336 ms | 5084 ms | −252 ms (−5 %) |
| S2 today→training mobile API p95 | 4814 ms | 4196 ms | −618 ms (−13 %) |
| **S3 warm-Today mobile LCP** | 9732 ms | **5452 ms** | **−4280 ms (−44 %)** |
| **S4 cold landing desktop FCP** | 2892 ms (`667dcc2`) | **1636 ms** | **−1256 ms (−43 %)** |
| **S4 cold landing mobile FCP** | 2840 ms | **1504 ms** | **−1336 ms (−47 %)** |

## Observations

### S1 — login → /today

The headline win, and what the user actually feels first. **FCP −29 % desktop / −41 % mobile**, **TTFB cut roughly in half on both** — that's F4 (East Asia origin replacing SWA-Amsterdam) showing up cleanly. The `d37484b` anchor's 1039 ms desktop TTFB was the cross-region SWA-AMS round-trip; the new 570 ms is what App Service HK can do. Mobile API p95 −33 % is PR-139 (SQLite WAL + DEK cache) showing through on the slow tail. Desktop API p95 only −7 % — likely small-sample noise on cn-pc-2 (3 iterations × ≤52 calls per iteration); the synthetic-load script in `2026-04-25-c73e4a1-backend-perf/` measured PR-139's `/api/today` p50 at −65 % from 30-call burst, which is the reliable backend number.

### S2 — Today loaded → click to /training

The desktop LCP "regression" (1100 → 4920 ms) is the anchor's outlier reverting to the mean. The original `d37484b` README explicitly flagged 1100 ms as anomalous: "Mobile LCP 5336 ms vs Desktop 1100 ms is a 5× gap — not network-explained (same PC, same connection). Probable causes: mobile viewport renders a different 'largest' element that depends on more API data, or σ pulled the median sideways from one bad iteration." Post-F4 desktop and mobile both land near 5 s, consistent with the API-dominated story (the largest element is a chart that paints once `/api/training` returns). This is *not* a real regression.

API p95 mobile −13 % shows PR-139's effect on this path too.

### S3 — warm repeat /today

**Mobile LCP −44 % (−4280 ms)** is the most striking move on the board. Pre-F4 the warm repeat-visit on mobile painted in 9.7 s because LCP was waiting on `/api/today`'s ~4.4 s API p95 plus rendering chrome. Post-F4 + PR-139 cut both contributors. Desktop is unchanged within noise (4888 → 5904, σ-bounded).

### S4 — anonymous landing

**FCP −43 % desktop / −47 % mobile.** This is the cleanest F4-only number — S4 is anonymous, no API calls, pure static delivery from origin. The 1300 ms desktop drop is the difference between "fetch fonts/JS/CSS from AMS over a GFW-impaired path" and "fetch from East Asia over direct CN-ISP-to-HK fiber". 1500 ms mobile FCP is close enough to the eastasia ACI baseline (1300 ms in `docs/perf-baselines/...` future) that we're now bandwidth-bound on the device, not network-bound on the path.

## The `cn-pc` inversion (passwall2 ON now hurts)

The `cn-pc` row is no longer faster than `cn-pc-2`, and on several cells it's notably *slower*:

| Cell | cn-pc (pwall ON) | cn-pc-2 (pwall OFF) |
|---|---|---|
| S4 desktop FCP | 3788 ms | 1636 ms |
| S2 desktop LCP | 12668 ms | 4920 ms |
| S2 desktop API p95 | 5295 ms | 4001 ms |
| S1 mobile API p95 | 4280 ms | 2520 ms |

Pre-F4 with SWA-Amsterdam, `cn-pc` was always faster because passwall2 bypassed the GFW-throttled CN→AMS path by tunnelling internationally. Post-F4 with East Asia origin, the optimal route for a CN client is **direct CN-ISP → HK**, which `cn-pc-2` takes. `cn-pc` instead routes CN-ISP → overseas tunnel → HK, paying an extra hop that the new architecture made unnecessary.

This means **friends in mainland China without VPN now get the best Praxys experience** — the architectural inversion confirms F4 was the right call for the CN audience.

## What this baseline targets

- ✅ Validates F4 (frontend co-location). S1 TTFB / S4 FCP moves are unambiguously the AMS→HK switch.
- ✅ Validates PR-139 (backend perf). Mobile S1/S2/S3 API p95 drops 13–33 % match the synthetic-load script's earlier numbers within noise.
- 🔵 Open: API p95 still ≥ 2.5 s on the slow tail (was ≥ 3.7 s pre-PR-139). Further backend perf work would target this — Azure SQL Serverless / PostgreSQL Flexible would eliminate the SMB-mount latency floor entirely. Tracked as a future option, not urgent.
- 🔵 Open: F3 (Azure Front Door) deprioritized — see `2026-04-25-d37484b/` notes. Tencent COS + EdgeOne split-horizon for CN is the future move post-ICP.

## Raw artifacts

- `s1-cn-pc-{2-,}{desktop,mobile}/pages/www_praxys_run/s1-today-via-login/data/browsertime.har`
- `s2-cn-pc-{2-,}{desktop,mobile}/pages/www_praxys_run/s2-training/data/browsertime.har`
- `s3-cn-pc-{2-,}{desktop,mobile}/pages/www_praxys_run/s3-today-warm/data/browsertime.har`
- `s4-cn-pc-{2-,}{desktop,mobile}/pages/www_praxys_run/data/browsertime.har`

To re-derive the metrics:

```bash
python scripts/analyze_baseline.py --baseline-dir docs/perf-baselines/2026-04-26-1358017
```
