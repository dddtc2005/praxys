# Baseline: 2026-04-25 — `667dcc22` (after Phase 1 #1: self-host fonts)

**Purpose:** measure the impact of Phase 1 #1 (PR #115 — self-host fonts via `@fontsource-variable/*`). Diffs against the anchor baseline at [`../2026-04-24-468ce25/`](../2026-04-24-468ce25/) (commit `e82e3cb`).

**Deploy state:** prod commit `667dcc22` (PR-M / vite-plugin-pwa merged). Frontend: `www.praxys.run` (SWA). Backend: `trainsight-app.azurewebsites.net` (App Service, East Asia). All Phase 1 fixes shipped: self-hosted fonts, code splitting (PR-K), API GZip (PR-H), cache-control headers (PR-I). Phase 2 fixes shipped: refetch-on-focus off (PR-J), settings dedupe (PR-L), PWA (PR-M).

**Run:** 2026-04-25 ~02:49–02:51 Asia/Shanghai, operator PC, **passwall2 OFF** (raw mainland-CN ISP path). 3 iterations per cell, sitespeed.io 39.5.0 inside Docker, Chrome 146. cn-pc (passwall ON / control) NOT re-run this round — the fix doesn't help paths that already reach Google, so the control row from the anchor baseline still applies as a comparison reference.

## Environment fingerprint

| Field | Anchor (e82e3cb) | This run (667dcc22) | Δ |
|---|---|---|---|
| Frontend URL | `https://www.praxys.run/` | same | — |
| API URL | `trainsight-app.azurewebsites.net` | same | — |
| CDN / Front Door | `none` | `none` | — |
| API GZip middleware | `off` | **on** | PR-H |
| Font hosting | Google Fonts external | **self-hosted via @fontsource** | **PR-G** |
| Route code splitting | none (1 monolithic bundle) | **React.lazy + manualChunks** | PR-K |
| Cache-control on `/assets/*` | SWA defaults | **`max-age=31536000, immutable`** | PR-I |
| `refetchOnWindowFocus` | `true` | `false` | PR-J |
| PWA / service worker | off | **on (auto-update)** | PR-M |

## Measurements (S4 — Anonymous Landing)

### cn-pc-2 — passwall2 OFF (real mainland-CN reality)

| Device | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB | Static KB | API KB | # reqs | # API | API p50 | API p95 | Protocol | Font CSS TTFB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Desktop | **2892** | **3168** | **1035** | 1013 | 1746.4 | 0.0 | 102 | 0 | — | — | h2 | — |
| Mobile  | **2788** | **3052** | **996**  | 983  | 1746.4 | 0.0 | 102 | 0 | — | — | h2 | — |

Run-to-run σ on FCP: 70 ms (Desktop), 99 ms (Mobile). Reproducible.

## Diff vs anchor baseline (cn-pc-2, 2026-04-24-468ce25)

| Metric | Device | Anchor | After | Δ | % | Forecast |
|---|---|---|---|---|---|---|
| **FCP** | Desktop | 22476 | **2892** | **-19584** | **-87.1%** | -19.4 s ✅ |
| **FCP** | Mobile  | 22532 | **2788** | **-19744** | **-87.6%** | -19.5 s ✅ |
| **LCP** | Desktop | 22476 | 3168 | -19308 | -85.9% | matches FCP collapse ✅ |
| **LCP** | Mobile  | 22532 | 3052 | -19480 | -86.5% | matches FCP collapse ✅ |
| **TTI** | Desktop | 22059 | 1035 | **-21024** | **-95.3%** | bigger than predicted ✅✅ |
| **TTI** | Mobile  | 22102 | 996  | **-21106** | **-95.5%** | bigger than predicted ✅✅ |
| HTML TTFB | Desktop | 1009 | 1013 | +4 | +0.4% | flat as predicted ✅ |
| HTML TTFB | Mobile  | 1039 | 983  | -56 | -5.4% | flat as predicted ✅ |
| Static KB | both | 1473 | 1746 | +273 | +18.5% | up — fonts now arrive (were timing out before) |
| # reqs | both | 42 | 102 | +60 | +143% | up — WOFF2 subsets now fetched (each ~60 KB) |
| Font CSS TTFB | both | — | — | — | — | absent because request no longer exists ✅ |

## Observations

1. **Forecast matched within 200 ms.** Pre-fix the operator PC (passwall ON, "control") sat at FCP ~3000 ms. Post-fix the real-CN PC sits at the same ~3000 ms — exactly what we'd expect when the only thing different (Google Fonts blocked vs reachable) becomes irrelevant because the fonts now ship from our origin.

2. **TTI win is bigger than the FCP win.** -21024 ms vs -19584 ms. Render-blocking CSS doesn't just delay paint — it delays JS handler wiring too, because Chrome's main thread can't proceed to script execution while it's waiting on a stylesheet that gates layout. Removing the blocker collapses both metrics together.

3. **Static KB +273 KB and # requests +60 are not regressions.** Pre-fix, the browser tried to fetch Google Fonts CSS + woff2 subsets, gave up after timeouts → 0 bytes for fonts, 0 successful font requests. Post-fix, the browser successfully fetches subsets it actually needs → ~273 KB of fonts arrive, +60 requests from the WOFF2 subset graph. Net: the page renders correctly (with the right font, not the OS fallback) for 273 KB of bytes that previously failed to arrive.

4. **The +60 requests issue is potentially addressable** by precaching the most-common WOFF2 subsets via PWA workbox. PR-M's Workbox config currently excludes WOFF2 from precache (intentional — 4.8 MB total, mostly Chinese subsets the average user never renders). A future tweak could opt the small Latin-only subsets into precache for the en-locale users.

5. **HTTP/2 still in use.** No HTTP/3 yet (would need Front Door — Phase 3). With +60 requests over HTTP/2 from a CN connection, head-of-line blocking on packet loss could be a tail-latency concern, but FCP σ is only 70 ms across runs, so it's not biting today.

6. **Mobile slightly faster than Desktop now.** 2788 vs 2892. Within run variance (σ 99 / 70). The GFW-induced gap that hurt mobile harder is gone — both form factors converge to the same ~3 s when the network path is clean.

## Lighthouse 13 (desktop, ad-hoc)

Operator ran Chrome DevTools → Lighthouse against `https://www.praxys.run/` on the same day. JSON saved as `www.praxys.run-20260425T110757.json`. Headlines:

| Category | Score |
|---|---|
| Performance | 75/100 |
| Accessibility | 96/100 |
| Best Practices | 81/100 |
| SEO | 100/100 |

| Audit | Value | Score |
|---|---|---|
| FCP | 2.2 s | 22/100 |
| LCP | 2.2 s | 56/100 |
| TBT | 0 ms | 100/100 |
| CLS | 0.001 | 100/100 |
| TTI | 2.2 s | 93/100 |

The low FCP/SI scores aren't real-world reflections — Lighthouse simulates Slow 4G even on fast connections, so any modern site picks up score penalties. The sitespeed.io numbers above are the truth-source for real-network behavior.

Audits Lighthouse still flagged that we haven't shipped fixes for:

- **Reduce unused JavaScript — est. 196 KiB**. Code splitting (PR-K) trimmed the initial load but the recharts chunk (113 KB gz) is the largest single chunk and could be lazy-loaded within Today rather than eager-imported.
- **Render-blocking requests — est. 260 ms**. The main CSS bundle (240 KB / 70 KB gz) is render-blocking; could split critical-above-fold from rest.
- **Page prevented back/forward cache restoration**. One unspecified reason — likely an event listener or the SW. bfcache restore is instant on back-button regardless of SW state, so worth investigating.
- **1 deprecated API warning**. Source not surfaced in summary; check the full JSON.

None are urgent — flagged here as the next-most-addressable items if/when Phase 1 gains aren't enough.

## Raw artifacts

HARs for this baseline are in the **`perfbaselines-archive`** Azure blob container (see `docs/perf-baselines/ci-setup.md` for retrieval). Cells captured by canonical path-pattern (after extraction):

- `s4-cn-pc-2-desktop/pages/www_praxys_run/data/browsertime.har` — full HAR, all 102 requests
- `s4-cn-pc-2-mobile/pages/www_praxys_run/data/browsertime.har` — same for mobile
- `www.praxys.run-20260425T110757.json` — Lighthouse 13 report, desktop form factor (kept in-repo, no auth headers)
- (videos / filmstrip / screenshots dropped via `.gitignore`)

To re-derive the sitespeed metrics after extracting the archive:

```bash
python scripts/analyze_baseline.py --baseline-dir docs/perf-baselines/2026-04-25-667dcc2
```
