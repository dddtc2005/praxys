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

## The three scenarios

Run all three for every baseline. Identical inputs → deltas attribute to code changes, not measurement noise.

- **S1 — Cold first load of Today page.** Empty cache, no service worker. Navigate to the homepage → log in → Today paints. The "new user" path.
- **S2 — Cold first load of Training page.** Same pre-conditions as S1 but navigate to `/training` — currently fires 7 API round-trips, our worst offender.
- **S3 — Warm repeat visit to Today.** Authenticated, cache populated (service worker active once Phase 2 #7 lands), tab revisit. The "daily use" path.

## What to capture per run

For each scenario × probe location:

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

For RUM, additionally segment by `navigator.connection.effectiveType` (4g / 3g / slow-2g / wifi). The telemetry initializer in `web/src/lib/appinsights.ts` attaches this to every event.

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
└── summary.md             — running table of all baselines, diff by phase
```

Each phase's PR description cites the row in `summary.md` that names the metrics that moved, by how much, and any that didn't move in the expected direction (= the fix didn't do what we thought).

## How to run a baseline

See [`../../scripts/run-baseline.md`](../../scripts/run-baseline.md) for the step-by-step WebPageTest checklist.
