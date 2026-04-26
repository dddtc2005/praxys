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

## Measurements (Tier 1)

Record the median of 3 runs per cell (WPT "Median" column, First View). Highlight anything that looks like a flaky outlier with `(flaky)` and note in the Observations section. Tier 1 matrix is 4 probes × 2 devices × 4 scenarios = 32 cells.

### S1 — Cold first load, Today page (via login)

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB | Static KB | API KB | # reqs | # API | API p50 | API p95 | Protocol | Font CSS TTFB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Beijing   | Desktop | | | | | | | | | | | | |
| Beijing   | Mobile  | | | | | | | | | | | | |
| Shanghai  | Desktop | | | | | | | | | | | | |
| Shanghai  | Mobile  | | | | | | | | | | | | |
| Hong Kong | Desktop | | | | | | | | | | | | |
| Hong Kong | Mobile  | | | | | | | | | | | | |
| US West   | Desktop | | | | | | | | | | | | |
| US West   | Mobile  | | | | | | | | | | | | |

### S2 — Cold first load, Training page (via login)

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB | Static KB | API KB | # reqs | # API | API p50 | API p95 | Protocol | Font CSS TTFB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Beijing   | Desktop | | | | | | | | | | | | |
| Beijing   | Mobile  | | | | | | | | | | | | |
| Shanghai  | Desktop | | | | | | | | | | | | |
| Shanghai  | Mobile  | | | | | | | | | | | | |
| Hong Kong | Desktop | | | | | | | | | | | | |
| Hong Kong | Mobile  | | | | | | | | | | | | |
| US West   | Desktop | | | | | | | | | | | | |
| US West   | Mobile  | | | | | | | | | | | | |

### S3 — Warm repeat visit, Today page

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB | Static KB | API KB | # reqs | # API | API p50 | API p95 | Protocol |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Beijing   | Desktop | | | | | | | | | | | |
| Beijing   | Mobile  | | | | | | | | | | | |
| Shanghai  | Desktop | | | | | | | | | | | |
| Shanghai  | Mobile  | | | | | | | | | | | |
| Hong Kong | Desktop | | | | | | | | | | | |
| Hong Kong | Mobile  | | | | | | | | | | | |
| US West   | Desktop | | | | | | | | | | | |
| US West   | Mobile  | | | | | | | | | | | |

### S4 — Anonymous Landing page

No login, no API calls (or one public health ping). Font CSS TTFB is the critical cell here — it's where Google-Fonts blocking in CN shows up loudest.

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB | Static KB | # reqs | Protocol | Font CSS TTFB |
|---|---|---|---|---|---|---|---|---|---|
| Beijing   | Desktop | | | | | | | | |
| Beijing   | Mobile  | | | | | | | | |
| Shanghai  | Desktop | | | | | | | | |
| Shanghai  | Mobile  | | | | | | | | |
| Hong Kong | Desktop | | | | | | | | |
| Hong Kong | Mobile  | | | | | | | | |
| US West   | Desktop | | | | | | | | |
| US West   | Mobile  | | | | | | | | |

## Tier 2 / Tier 3 runs (if any were done this baseline)

Tier 2 and Tier 3 are optional per baseline — only fill in if actually captured. Use free-form tables or prose; link artifact paths in this directory.

## Observations

- Surprising values (+ why you think it happened)
- Flaky runs (+ what you did about them)
- Anything that looks broken (e.g. "font CSS timed out at 30s in Shanghai")

## Diff vs previous baseline

If this is a "before" anchor, skip. If this is "after Phase X #Y", name the previous baseline here and list metrics that moved. Call out desktop vs mobile separately where they diverge — fixes often land on one form factor before the other.

- `S4 FCP Beijing Desktop: 8400ms → 820ms (-7580ms, -90%)` ✅ matches font-self-host prediction
- `S4 FCP Beijing Mobile:  11200ms → 1150ms (-10050ms, -90%)` ✅ same pattern, worse baseline
- `S2 API KB Training (any device): 48 KB → 11 KB (-77%)` ✅ matches gzip prediction
- `S2 p95 API Beijing Mobile: no change` ⚠️ expected move from Phase 2 #4 — investigate

## Raw artifacts

**HARs are not committed alongside this README.** Per the HAR storage policy in `docs/perf-baselines/ci-setup.md`, raw HARs live in:

- **GitHub Actions artifacts** (`baseline-<cell>-<run-id>` / `baseline-combined-<run-id>`) for 30 days post-run
- **Azure blob `perfbaselines-archive`** on `stperftrainsight` for long-term durability

Lighthouse JSON / filmstrip / Lighthouse-13 reports are also kept out of the repo via `.gitignore` (heavy binary, regenerable).

For this baseline, list the cells that were captured by their canonical path-pattern below so a future operator can locate them after extraction:

- `sN-<probe>-<device>/pages/<slug>/[<measure-name>/]data/browsertime.har`

Example cells captured: ...
