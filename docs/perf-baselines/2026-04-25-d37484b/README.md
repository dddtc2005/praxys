# Baseline: 2026-04-25 — `d37484b` (S1/S2/S3 anchor before F2)

**Purpose:** first capture of the login-required scenarios (S1/S2/S3) post-F1. Becomes the diff target for F2 (Training waterfall collapse) and any subsequent fix that touches API endpoints.

**Deploy state:** prod commit `d37484b` (PR-127 / F1 merged — login-scripted scenarios). All Phase 1 + Phase 2 fixes from the previous batch are live: self-hosted fonts, code splitting, FastAPI GZip, cache-control headers, refetch-on-focus disabled, /api/settings dedupe, PWA. AI insight endpoint (`/api/insights/training_review`) still rule-based today; LLM transition tracked in issue #103.

**Run:** 2026-04-25 ~04:?? Asia/Shanghai, operator PC, **passwall2 OFF** (raw mainland-CN ISP path). 3 iterations per cell. Login uses the public demo account (`demo@trainsight.dev`).

## Measurements

### S1 — Cold first load, Today page (via login)

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB | Static KB | API KB | # reqs | # API | API p50 | API p95 | Protocol | Font CSS TTFB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cn-pc-2 | Desktop | 2892 | 2892 | 1059 | 1039 | 2361.0 | 45.6 | 108 | 54 | 186 | **4112** | h2 | — |
| cn-pc-2 | Mobile  | 2840 | 2840 | 1010 |  984 | 1910.3 | 34.8 |  97 | 52 | 175 | **3759** | h2 | — |

### S2 — Cold first load, Training page (via login)

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB | Static KB | API KB | # reqs | # API | API p50 | API p95 | Protocol | Font CSS TTFB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cn-pc-2 | Desktop |  568 | 1100 |  19 |    5 |  240.8 | 37.0 | 59 | 46 | 143 | **4102** | h2 | — |
| cn-pc-2 | Mobile  |  500 | 5336 |  25 |    9 |  922.4 | 50.8 | 81 | 54 | 137 | **4814** | h2 | — |

### S3 — Warm repeat visit, Today page

| Probe | Device | FCP (ms) | LCP (ms) | TTI (ms) | HTML TTFB | Static KB | API KB | # reqs | # API | API p50 | API p95 | Protocol | Font CSS TTFB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| cn-pc-2 | Desktop |  508 | 4888 |  20 |    8 |  334.8 | 45.6 | 64 | 48 | 145 | **4147** | h2 | — |
| cn-pc-2 | Mobile  |  440 | 9732 |  21 |    7 |  902.1 | 45.6 | 75 | 48 | 158 | **4398** | h2 | — |

## Observations

### S1 — login → /today

FCP 2892 ms desktop matches the S4 anchor (`2026-04-25-667dcc2`) FCP exactly — Phase 1's font-self-host win carries through to the logged-in cold path. The difference is API count (54 vs 0 on S4) and total static (2361 KB vs 1746 KB; the extra ~600 KB is woff2 subsets fetched for character ranges not exercised on Landing).

**API p95 is the headline issue: 4112 ms desktop / 3759 ms mobile.** Some endpoint in the /today render path takes ≥4 s on its slowest run. Most likely candidates: `/api/insights/training_review`, `/api/today`, or something the dashboard fetches on mount. Worth a server-side audit if API p95 doesn't drop after F2.

### S2 — Today loaded → click to /training

S2's preScript logs in, lets /today complete, then navigates to /training and measures THAT navigation. So S2 is "Today→Training transition", not "fresh Training cold load". This matches the realistic user flow: post-login lands on /today, user clicks "Training" in nav.

FCP 568 ms desktop is fast because the SPA shell + vendor chunks are already cached from /today. TTFB 5 ms confirms the SPA history-API navigation (no HTML fetch). Static KB only 241 KB on desktop = the lazy Training chunk + its CSS.

**Mobile LCP 5336 ms vs Desktop 1100 ms is a 5× gap** — not network-explained (same PC, same connection). Probable causes: mobile viewport renders a different "largest" element that depends on more API data, or σ pulled the median sideways from one bad iteration. Worth investigating once F2 ships and we can re-run.

API p95 ~4-5 s on Training is exactly what F2 targets — collapsing /api/plan/stryd-status into /api/plan removes one chance for a slow tail.

### S3 — warm Today repeat visit

**FCP 508 ms desktop / 440 ms mobile, TTFB 8 ms / 7 ms.** The PWA service worker is doing what we built it for — shell loads from disk-cache, no network round-trip. Compare to S1's TTFB 1039 / 984 ms (same /today, fresh navigation). PR-M earned this.

**LCP 4888 / 9732 ms is the painful counterpoint.** Even with zero network for shell, LCP fires when the largest content (a chart or stat card) is rendered, which depends on `/api/today` returning. With API p95 at 4147 ms, "warm" Today still feels slow because the API tail dominates LCP. Service worker can't cache API responses (we'd lose data freshness) — fixing this means making the API itself faster.

Mobile S3 LCP 9732 ms is the worst single number on the board. Probably one bad iteration; would need σ to confirm.

## What this baseline targets

- **F2 (Training waterfall collapse — narrowed scope):** merge `/api/plan/stryd-status` into `/api/plan` only. **Skip merging `/api/insights/training_review`** because issue #103 plans an LLM transition for that endpoint; inlining it would force every /api/training response to wait for an LLM call. Decoupling preserves the option to make the AI insight async/streaming/cached.
  - Predicted move: S2 # API drops by 1, API p95 may drop modestly (one fewer endpoint = one fewer tail risk).

- **Anything that improves /api/today** (server tier bump, slow-query audit, or DB index work) would move S1 + S3's LCP down.

- **Anything that improves /api/insights/training_review** specifically would also help S1 (Today's render path includes it via AiInsightsCard on Training, but Today might also fetch it... need to confirm).

## Raw artifacts

HARs for this baseline are in the **`perfbaselines-archive`** Azure blob container (see `docs/perf-baselines/ci-setup.md` for retrieval). Cells captured by canonical path-pattern (after extraction):

- `s1-cn-pc-2-{desktop,mobile}/pages/www_praxys_run/s1-today-via-login/data/browsertime.har`
- `s2-cn-pc-2-{desktop,mobile}/pages/www_praxys_run/s2-training/data/browsertime.har`
- `s3-cn-pc-2-{desktop,mobile}/pages/www_praxys_run/s3-today-warm/data/browsertime.har`
- (videos / filmstrip / screenshots dropped via `.gitignore`)

To re-derive the metrics after extracting the archive:

```bash
python scripts/analyze_baseline.py --baseline-dir docs/perf-baselines/2026-04-25-d37484b
```
