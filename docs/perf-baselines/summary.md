# Perf arc summary — pre-arc → post-L3

**TL;DR.** Two weeks of perf work cut user-visible page time by 38–94 % across every login-gated scenario, and turned the cold anonymous-landing experience for CN-without-VPN visitors from "site looks broken" (22 s blank screen) into "site is fast" (1.6 s render). Warm repeat /today is now essentially instant — second-visit API responses return in 0.25 s end-to-end. This doc is the one-page shareable summary; per-anchor detail is in `<YYYY-MM-DD>-<sha>/README.md` directories and the running narrative is in [`2026-04-26-checkpoint.md`](./2026-04-26-checkpoint.md).

## Headline numbers (cn-pc-2 — real mainland-CN ISP, no VPN)

Median of 3 iterations per cell, sitespeed.io 39.5.0 inside Docker.

| Scenario                 | Metric  | Desktop                          | Mobile                          |
|--------------------------|---------|----------------------------------|---------------------------------|
| Anonymous landing (cold) | FCP     | 22.5 s → **1.6 s** (−93 %)       | 22.5 s → **1.7 s** (−92 %)      |
| Cold login → Today       | FCP     | 2.9 s → **1.7 s** (−43 %)        | 2.8 s → **1.8 s** (−38 %)       |
| Cold login → Today       | API p95 | 4.1 s → **1.3 s** (−68 %)        | 3.8 s → **1.2 s** (−67 %)       |
| Cold Today → Training    | LCP     | (pre-arc outlier — n/a)          | 5.3 s → **2.4 s** (−54 %)       |
| Cold Today → Training    | API p95 | 4.1 s → **1.9 s** (−55 %)        | 4.8 s → **1.7 s** (−64 %)       |
| Warm repeat Today        | LCP     | 4.9 s → **1.4 s** (−71 %)        | 9.7 s → **1.4 s** (−85 %)       |
| Warm repeat Today        | API p95 | 4.1 s → **0.3 s** (−93 %)        | 4.4 s → **0.25 s** (−94 %)      |

**Anchors.** "Before" pre-arc anchors differ by scenario: anonymous landing (S4) compares against `2026-04-24-468ce25/` (the rawest committed baseline, pre-Phase-1, before any work landed); login-gated scenarios (S1/S2/S3) compare against `2026-04-25-d37484b/` (the oldest login-scripted baseline; Phase 1 was already in by then because login-scripting required login-flow work to land first). "After" is `2026-04-27-981b657/` (post-L3 deploy, all backend work landed).

## What landed (rough chronology)

| Layer | What | Headline contribution |
|---|---|---|
| Phase 1 #1 | Self-hosted fonts (eliminated GFW-blocked Google Fonts) | Most of the −21 s on cold anonymous landing |
| Phase 1 #2-4 | Vendor-chunk code splitting, FastAPI GZip, cache-control headers, PWA precache | Smaller bundle on cold; warm visits read shell from disk |
| F2 (#132) | Collapsed `/api/plan/stryd-status` into `/api/plan` | Removed one round-trip on Training cold load |
| F4 (#141, #142) | Frontend off SWA-Amsterdam onto Azure App Service East Asia (HK) | −575 ms TTFB on every cold visit |
| PR-139 | SQLite WAL pragmas + 20 MB page cache + per-DEK unwrap LRU cache | −33 to −65 % API p95 |
| L1 (#146) | Refactored kitchen-sink `get_dashboard_data` into per-endpoint slim packs | Eliminated 60-85 % of work-per-request that was previously thrown away |
| L2 (#147) | ETag/304 revalidation per slim pack (per-(user,scope) `cache_revisions` counter) | Warm repeat /today returns 304 in ~17 ms p50 server-side |
| L3 (#148) | Materialized per-section dashboard cache at sync_writer commit; reads become indexed SELECTs | Cold reads no longer recompute; second-visit Today is effectively instant |

## Outcomes that matter for users

- **Cold anonymous landing −21 s** for CN-without-VPN. Before: browser timed out fetching Google Fonts CSS, page sat blank for 22+ seconds. After: 1.6 s to first paint. Difference between "this site is broken" and "this site loads fast" for a first-time visitor.
- **Warm repeat Today −85 % mobile LCP** (9.7 s → 1.4 s). The most-frequent path — a returning user reopening Today from a notification or browser tab — is now snappy.
- **Architectural inversion**: pre-F4, friends with VPN had a faster experience because the VPN tunnel bypassed the GFW-throttled CN→Amsterdam path that Static Web Apps was forcing. Post-F4 with origin in East Asia (HK), friends *without* VPN now have the optimal path; VPN routing pays an unnecessary extra hop. This was the right call for the audience.

## Where to find detail

- **[`2026-04-26-checkpoint.md`](./2026-04-26-checkpoint.md)** — full narrative across the entire arc, layer-by-layer attribution, server-side App Insights numbers, cn-pc + cn-pc-2 + eastasia tables, post-L1 / post-L2 / post-L3 measurements.
- **[`2026-04-24-468ce25/README.md`](./2026-04-24-468ce25/README.md)** — the rawest committed pre-arc anchor.
- **[`2026-04-25-d37484b/README.md`](./2026-04-25-d37484b/README.md)** — first login-scripted (S1/S2/S3) anchor.
- **[`2026-04-26-1358017/README.md`](./2026-04-26-1358017/README.md)** — post-F4 + PR-139 anchor (immediately before L1/L2/L3).
- **[`2026-04-27-981b657/README.md`](./2026-04-27-981b657/README.md)** — post-L3 anchor (this summary's "after" column).

## Methodology

cn-pc-2 = an operator PC in Shanghai with **passwall2 OFF** (raw mainland-CN ISP path, what real users without VPN experience). 3 iterations per cell, sitespeed.io 39.5.0 inside Docker, Chrome latest. Median values reported. Login-scripted scenarios use the public demo account (`demo@trainsight.dev / demo`) — same defaults as Landing's "Try the demo" CTA.

For the per-cell raw outputs see the per-anchor `README.md` files. HARs are not committed (they contain JWT bearer tokens); they live in the private Azure blob `perfbaselines-archive` per [`ci-setup.md`](./ci-setup.md) for cloud-run baselines, and are kept ephemeral on operator PCs for local-run baselines.
