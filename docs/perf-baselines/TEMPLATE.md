# Baseline: YYYY-MM-DD — `<short-sha>`

**Purpose of this run:** e.g. "Anchor before any optimization" / "After Phase 1 #1 (self-host fonts)"
**Deploy state:** prod commit `<full-sha>`, frontend build `<hash>`, backend build `<hash>`
**Run started at:** `YYYY-MM-DD HH:mm:ss Asia/Shanghai` (note: peak GFW congestion ≈ 20:00–23:00 Beijing; pick a consistent slot across baselines)
**Operator:** `<name>`

## Environment fingerprint

| Field | Value |
|---|---|
| Frontend URL | |
| API URL | |
| CDN / Front Door | `none` / `AFD Standard` / ... |
| SWA compression | `auto-brotli` |
| API GZip middleware | `off` / `on` |
| Font hosting | `Google Fonts` / `self-hosted` |
| Route code splitting | `none` / `React.lazy` |
| PWA / service worker | `off` / `on` |

## Measurements

Record the median of 3 runs per cell (WPT "Median" column, First View). Highlight anything that looks like a flaky outlier with `(flaky)` and note below.

### S1 — Cold first load, Today page

| Probe | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB (ms) | Static KB | API KB | # reqs | # API reqs | API p50 | API p95 | Protocol | Font CSS TTFB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Beijing  | | | | | | | | | | | | |
| Shanghai | | | | | | | | | | | | |
| Hong Kong| | | | | | | | | | | | |
| US West  | | | | | | | | | | | | |

### S2 — Cold first load, Training page

| Probe | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB (ms) | Static KB | API KB | # reqs | # API reqs | API p50 | API p95 | Protocol | Font CSS TTFB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Beijing  | | | | | | | | | | | | |
| Shanghai | | | | | | | | | | | | |
| Hong Kong| | | | | | | | | | | | |
| US West  | | | | | | | | | | | | |

### S3 — Warm repeat visit, Today page

| Probe | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB (ms) | Static KB | API KB | # reqs | # API reqs | API p50 | API p95 | Protocol |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Beijing  | | | | | | | | | | | |
| Shanghai | | | | | | | | | | | |
| Hong Kong| | | | | | | | | | | |
| US West  | | | | | | | | | | | |

## Observations

- Surprising values (+ why you think it happened)
- Flaky runs (+ what you did about them)
- Anything that looks broken (e.g. "font CSS timed out at 30s in Shanghai")

## Diff vs previous baseline

If this is a "before" anchor, skip. If this is "after Phase X #Y", name the previous baseline here and list metrics that moved:

- `FCP Beijing: 12800ms → 3100ms (-9700ms, -76%)` ✅ matches prediction
- `API KB Training: 48 KB → 11 KB (-77%)` ✅ matches gzip prediction
- `p95 API Beijing: no change` ⚠️ expected move from Phase 2 #4 — investigate

## Raw artifacts

Saved in this directory:
- `sX-<probe>.har` — full network HAR export
- `sX-<probe>.lighthouse.json` — Lighthouse JSON report
- `sX-<probe>.filmstrip.png` — filmstrip screenshot strip (visual sanity check)
- `sX-<probe>.wpt-link` — permalink to the WebPageTest result page
