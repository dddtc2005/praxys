# Baseline: 2026-04-24 — `468ce25`

**Purpose:** anchor before any Phase 1 optimization. Every Phase 1/2/3 fix will diff against this row.

**Deploy state:** prod commit `49027f46` (PR-E merged to main, pre-any-perf-fix). Frontend: `www.praxys.run` (SWA). Backend: `trainsight-app.azurewebsites.net` (App Service, East Asia).

**Run:** 2026-04-24 ~15:36–15:45 Asia/Shanghai (CN afternoon, not peak), from an operator's PC in mainland China. Chrome 146.0.7680.80 inside sitespeed.io 39.5.0 Docker image. 3 iterations per cell, median reported.

**Probes:**
- **`cn-pc`** — PC with **passwall2 ON** on the router: Google Fonts (and everything else external) routed through an overseas tunnel. This is the operator's normal dev-work config, and a useful "app without GFW" control.
- **`cn-pc-2`** — PC with **passwall2 OFF**: raw CN ISP path, no tunnel. This is what a real mainland-user visiting the site sees.

## Environment fingerprint

| Field | Value |
|---|---|
| Frontend URL | `https://www.praxys.run/` |
| API URL | `https://trainsight-app.azurewebsites.net/` |
| CDN / Front Door | `none` |
| SWA compression | `auto-brotli` |
| API GZip middleware | `off` — Phase 1 #3 will turn this on |
| Font hosting | `Google Fonts` (via `<link href="https://fonts.googleapis.com/css2?...">` in `web/index.html`) |
| Route code splitting | `none` — monolithic bundle (all 8 pages + recharts + react-markdown + tanstack-query in one file) |
| PWA / service worker | `off` |

## Measurements (Tier 1 subset — S4 only)

S1/S2/S3 (login-required scenarios) land in a follow-up; S4 (Anonymous Landing) alone is enough to attribute Phase 1 #1 (self-host fonts) because that fix lives entirely on the render path.

### S4 — Anonymous Landing page

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB | Static KB | API KB | # reqs | # API | API p50 | API p95 | Protocol | Font CSS TTFB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cn-pc    | Desktop | 3000  | 3152  | 1407  | 1040 | 2379.2 | 0.0 | 52 | 0 | — | — | h2 | 108 |
| cn-pc    | Mobile  | 3264  | 3264  | 1214  | 957  | 2319.6 | 0.0 | 53 | 0 | — | — | h2 | 80  |
| cn-pc-2  | Desktop | **22476** | **22476** | 22059 | 1009 | 1473.3 | 0.0 | 42 | 0 | — | — | h2 | **—** |
| cn-pc-2  | Mobile  | **22532** | **22532** | 22102 | 1039 | 1473.2 | 0.0 | 42 | 0 | — | — | h2 | **—** |

All numbers are medians over 3 runs. Run-to-run σ was tight (14–62 ms on desktop, up to 232 ms on mobile) — the `cn-pc-2` 22.5s is reproducible, not flaky.

## Observations

1. **The HTML document itself is fine on real CN.** TTFB is ~1s on both probes — Azure East Asia → mainland-CN ISP delivers the landing-page HTML cleanly. The GFW is not slowing the root document.

2. **The 19.4-second FCP gap (3.0s → 22.5s) is entirely render-blocking external resources.** Static-KB drops from ~2370 → 1473 KB (-900 KB); request count drops from 52 → 42 (-10 requests). The 10 missing requests and 900 missing KB are the Google Fonts CSS + the WOFF2 files it would have loaded. Font CSS TTFB shows `—` on `cn-pc-2` because no HAR entry exists — the browser gave up at DNS/TCP level before anything was attempted.

3. **Phase 1 #1 prediction.** Self-hosting fonts should cut `cn-pc-2` FCP from 22476 → roughly 3000 ms — an **~87% reduction**, saving ~19.4 s per cold page-load for every mainland user. This is the highest-leverage perf fix by far.

4. **Desktop vs Mobile is ~60 ms apart on the real CN probe.** Makes sense — the blocker is the same stylesheet, viewport-independent. Both form factors will benefit identically from #1.

5. **`cn-pc` "best case" still has 3-second FCP.** Even with the GFW bypassed entirely, the site takes 3s to first paint. That's the ceiling Phase 1 can reach for CN users — fixes #2 (code splitting), #3 (API GZip — not measured in S4), and #7 (PWA) will lower it further; the Hong Kong ACI probe from PR-F will show what Azure East Asia users without GFW look like.

## Diff vs previous baseline

N/A — first anchor.

## Raw artifacts

Kept in this directory (gitignored beyond what's listed):
- `s4-<probe>-<device>/pages/www_praxys_run/data/browsertime.har` — full network HAR per cell (gitignore whitelists these)
- This `README.md` — analyzer output + context

Skipped (see repo `.gitignore`):
- MP4 videos, filmstrip JPGs, key-event screenshots — heavy, not diff-useful
- Sitespeed.io's HTML viewer bundle — duplicated across every cell, not baseline data

To regenerate the metrics from the HARs:
```bash
python scripts/analyze_baseline.py --baseline-dir docs/perf-baselines/2026-04-24-468ce25
```
