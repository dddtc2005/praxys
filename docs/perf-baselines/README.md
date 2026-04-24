# Performance Baselines

Numbers, not opinions. Every performance fix lands with a before/after row in this directory so we can attribute each change to a measurable delta.

## Why this exists

Mainland-China users cross the Great Firewall to hit our Azure East Asia deployment. Perceived slowness has multiple causes (render-blocking Google Fonts, no API compression, 1.3 MB monolithic bundle, 7-request Training waterfall, HTTP/2-over-lossy-TCP, no PWA). To know which fix bought which seconds, we need reproducible before/after measurements.

## Three measurement layers

| Layer | Purpose | Tool | When |
|---|---|---|---|
| **Lab synthetic** | Catch code regressions in controlled conditions | Lighthouse CI in GitHub Actions | On every `web/**` PR (added in a later phase) |
| **Multi-region synthetic** | Ground truth for each phase's delta | WebPageTest — Beijing, Shanghai, Hong Kong, US West | Before & after each phase merges |
| **Production RUM** | Real user experience over time | Azure Application Insights (wired in `api/main.py` + `web/src/lib/appinsights.ts`) | Continuous, once `APPLICATIONINSIGHTS_CONNECTION_STRING` is set |

Azure Availability Tests (cheap URL pings from multiple Azure regions) provide an always-on uptime + TTFB baseline — see [`azure-provisioning.md`](./azure-provisioning.md) to set them up.

## The scenarios

Run all four for every baseline. Identical inputs → deltas attribute to code changes, not measurement noise.

- **S1 — Cold first load of Today page.** Empty cache, no service worker. Navigate to the homepage → log in → Today paints. The "new user" path.
- **S2 — Cold first load of Training page.** Same pre-conditions as S1 but navigate to `/training` — currently fires 7 API round-trips, our worst offender.
- **S3 — Warm repeat visit to Today.** Authenticated, cache populated (service worker active once Phase 2 #7 lands), tab revisit. The "daily use" path.
- **S4 — Anonymous Landing page.** Empty cache, not logged in. Navigate to `/` and measure. Critical for seeing Google Fonts blocking in isolation — this is the first impression for every new visitor, and it's also what WeChat-shared links open into.

## Test-matrix tiers

You can't meaningfully run every (geography × device × browser × network × scenario) combination for every PR. The matrix below is split by cost-of-drift: Tier 1 runs for every baseline so deltas are attributable; Tier 2 runs periodically to catch drift the core misses; Tier 3 is ad-hoc when investigating a specific bug.

### Tier 1 — every baseline (before/after each perf fix)

| Axis | Value |
|---|---|
| Geography | Beijing, Shanghai, Hong Kong, US West |
| Device | Desktop Chrome (1920×1080), Mobile Chrome (iPhone 14-class emulation) |
| Browser | Chrome latest |
| Network | Native (the probe's real connection — not throttled) |
| Scenario | S1, S2, S3, S4 |
| Time-of-day | 20:00–21:00 Asia/Shanghai (CN evening peak when GFW is worst) |
| Runs per cell | 3 (WPT computes median) |

**Cell count:** 4 geographies × 2 devices × 4 scenarios = **32 cells per baseline**. Both desktop and mobile are non-optional — users hit this app from both laptops (training analysis) and phones (daily check-in), and they can regress independently.

### Tier 2 — periodic (every 2–4 baselines or pre-release)

Catches what Tier 1 misses without bloating the per-fix loop:

- **WeChat embedded browser (X5) from Beijing + Shanghai** — uniquely Chinese reality. Shared links from WeChat open in the X5 in-app browser, which has its own font-loading, cache, and JS-bridge quirks. WPT doesn't ship a WeChat-browser location, so this runs via an Alibaba Cloud Beijing VM with Android + WeChat + remote-DevTools capture. One-time setup, then scriptable.
- **Safari (iOS emulation) from 2 probes** — iOS users are a big CN segment; catches WebKit-specific bundle / CSS / Intl issues.
- **Tablet viewport from 1 probe** — catches responsive-layout regressions on charts and grids.
- **Throttled 3G from Hong Kong** — stress test for payload size, isolated from GFW noise by using HK as the base probe.

### Tier 3 — ad-hoc investigations

Use when chasing a specific bug, rolling a region, or answering a targeted question. Not run on every baseline.

- Other CN cities (Shenzhen, Chengdu, Chongqing) — different ISP peering
- Edge, Firefox, UC Browser, QQ Browser
- Off-peak comparison (07:00 Asia/Shanghai) to quantify GFW variance
- Accessibility / reduced-motion profile audits
- Custom HAR + devtools-protocol trace capture for deep-dive diffs

### What RUM covers automatically

The Application Insights wire (backend + SPA) segments the real user population by browser, OS, device type, country, and `customDimensions.netinfo_effectiveType`. Every real browser / network shows up in production data without us synthesizing it. The synthetic Tier 1/2/3 matrix exists for **reproducibility** (a fix's delta must be attributable), not for coverage of every user configuration.

## What to capture per run

For each Tier 1 cell (scenario × probe × device — 32 cells total):

| Metric | Why it matters | Units |
|---|---|---|
| **FCP** (First Contentful Paint) | Catches Google Fonts blocking, render-blocking CSS | ms |
| **LCP** (Largest Contentful Paint) | Overall page readiness | ms |
| **TTI** (Time to Interactive) | When JS is done parsing & handlers are wired | ms |
| **TTFB** (Time to First Byte) for HTML | Server + GFW crossing | ms |
| **Transferred bytes — static** | Bundle + CSS + fonts on the wire (post-compression) | KB |
| **Transferred bytes — API** | Sum of all API responses during load | KB |
| **# requests — total** | Proxy for round-trip count across GFW | count |
| **# requests — API** | Specifically the API waterfall | count |
| **API p50 TTFB** | Median cross-GFW API time | ms |
| **API p95 TTFB** | Tail of cross-GFW API time (sensitive to packet loss) | ms |
| **Protocol** | Proves HTTP/3 rollout | `h2` / `h3` |
| **Font CSS TTFB** (isolated) | Specifically catches the Google Fonts block | ms or `timeout` |

For RUM, additionally segment by `customDimensions.netinfo_effectiveType` (4g / 3g / slow-2g / wifi). The telemetry initializer in `web/src/lib/appinsights.ts` attaches the full `navigator.connection` snapshot to every event, namespaced under `netinfo_*` to avoid shadowing SDK-native envelope fields.

## Directory layout

```
docs/perf-baselines/
├── README.md              — this file
├── TEMPLATE.md            — copy per run
├── azure-provisioning.md  — one-time user setup steps
├── 2026-04-24-<sha>/      — baseline before any optimization
│   ├── s1-beijing.har
│   ├── s1-beijing.lighthouse.json
│   ├── s1-beijing.filmstrip.png
│   ├── s2-shanghai.har
│   └── ... (one HAR / LH / filmstrip per scenario × probe)
├── 2026-MM-DD-<sha>/      — after Phase 1 fix #1 (self-host fonts)
│   └── ...
└── summary.md             — running table of all baselines (created on first real baseline run)
```

Each phase's PR description cites the row in `summary.md` that names the metrics that moved, by how much, and any that didn't move in the expected direction (= the fix didn't do what we thought).

## How to run a baseline

See [`../../scripts/run-baseline.md`](../../scripts/run-baseline.md) for the step-by-step WebPageTest checklist.
