# Running a Performance Baseline

Step-by-step for capturing a before/after snapshot using WebPageTest. Expect ~30–40 minutes end-to-end for 3 scenarios × 4 probe locations.

## Tools

- **WebPageTest** (webpagetest.org) — free tier gives 200 runs/month; paid API is ~$0.10–0.30/run if you blow through the free tier. Create an account to get an API key for scripted use.
- **17ce.com** or **boce.com** (optional fallback) — free CN-only TTFB probe if WPT Beijing/Shanghai are unavailable. Doesn't give LCP/FCP.

## Probe locations (in order)

WPT's hosted location IDs drift as contributors come and go. Re-check `https://www.webpagetest.org/getLocations.php` before each run — don't assume any specific ID below is still live.

| Location | Role | Example WPT location string (verify before run) |
|---|---|---|
| Beijing | Real CN mobile, China Mobile/Unicom backbone | `Beijing:Chrome` (availability varies; try `China:Chrome`) |
| Shanghai | Real CN mobile, China Telecom backbone | `Shanghai:Chrome` |
| Hong Kong | Azure origin region — isolates server/bundle from GFW | `HongKong:Chrome` |
| US West | Global control — catches regressions that hurt everyone | `ec2-us-west-1:Chrome` (AWS-hosted WPT nodes use `ec2-<region>:Chrome`) |

Note: `Dulles:Chrome` is WPT's default but it's on the US **East** Coast (Dulles, VA) — don't use it as a "US West" fallback. If `ec2-us-west-1` isn't currently offered, pick any West-Coast equivalent from the live list (Oregon, California) and record the exact ID in the baseline doc so future runs reproduce.

If a CN location is flaky or unavailable on the day, note it in the baseline doc and fall back to 17ce.com for TTFB-only, or spin up an Alibaba Cloud Beijing VM with headless Chrome + Lighthouse as a one-off (~1 hour setup). Don't substitute a different city silently — consistency across baselines matters.

## Timing discipline

Run all probes in the same calendar hour, **every baseline**. Recommended slot: **20:00–21:00 Asia/Shanghai** (Beijing evening peak — GFW is at its worst, so your numbers reflect the pessimistic real-user case).

## The three scenarios

Definitions live in `docs/perf-baselines/README.md`. Quick recap:
- **S1** — Cold Today page (fresh profile, logged out → login → Today paint)
- **S2** — Cold Training page (fresh profile, logged out → login → Training paint)
- **S3** — Warm Today page (logged in, cache warm, tab revisit)

## Script per scenario (WebPageTest UI)

Use **Scripted** test mode for S1 and S2 (to chain login + navigate). S3 uses **Repeat View** of S1's script.

### S1 script (paste into "Script" field)

```
setEventName Step1_Homepage
navigate https://<your-production-domain>/

setEventName Step2_Login
setValue name=email your-perf-test@example.com
setValue name=password <test-password>
submitForm

setEventName Step3_Today
waitFor document.readyState == "complete"
```

Set advanced options:
- **Connection:** `Native Connection` (don't throttle; you want real CN-mobile reality from the probe)
- **Number of runs:** 3 (WPT medians for you)
- **Capture Video:** on (for filmstrips)
- **Capture HAR:** on
- **Lighthouse:** on (captures the Lighthouse audit at the end)

### S2 script

Same as S1 but replace the final navigate with `navigate https://<your-production-domain>/training`.

### S3 script

Use WPT's **"Repeat View"** feature on the S1 script — it re-runs the test with cache populated from the first-view. Capture the Repeat View metrics row only.

## What to save per run

Create `docs/perf-baselines/<YYYY-MM-DD>-<short-sha>/` first. Then for each scenario × probe:

- **HAR file:** WPT result page → "Export HAR" → save as `s1-beijing.har`
- **Lighthouse JSON:** WPT result page → "Lighthouse" tab → download JSON → save as `s1-beijing.lighthouse.json`
- **Filmstrip:** WPT result page → "Filmstrip View" → right-click save the composite image → save as `s1-beijing.filmstrip.png`
- **WPT permalink:** copy the `https://www.webpagetest.org/result/...` URL → save as plain text in `s1-beijing.wpt-link`

## Filling in TEMPLATE.md

1. `cp docs/perf-baselines/TEMPLATE.md docs/perf-baselines/<YYYY-MM-DD>-<sha>/README.md`
2. Fill the environment fingerprint from the current deploy state.
3. For each row (probe × scenario), read values from the Lighthouse JSON and the HAR:
   - **FCP / LCP / TTI / HTML TTFB** — Lighthouse JSON → `audits.metrics.details.items[0]`
   - **Static KB / API KB** — HAR → sum `response.content.size` where `request.url` matches domain vs `/api/*`
   - **# reqs / # API reqs** — HAR → count entries, split on `/api/*`
   - **API p50 / p95** — HAR → for entries matching `/api/*`, compute percentiles of `timings.wait + timings.receive`
   - **Protocol** — HAR → `_securityState` or `response.httpVersion` (look for `h2` / `h3`)
   - **Font CSS TTFB** — HAR → row for `fonts.googleapis.com/css2?...` → `timings.wait` (if timeout, write `timeout`)
4. Note observations + flaky cells at the bottom.
5. Update `docs/perf-baselines/summary.md` with a one-row-per-phase rollup (create if missing).

## Commit convention

Each baseline lands in its own commit — not bundled with the code PR it measures. The code PR description links to the baseline commit for the "after" numbers.

Commit subject: `Perf baseline: <reason>` — e.g. `Perf baseline: anchor before optimization` or `Perf baseline: after Phase 1 #1 (self-host fonts)`.

## If you hit weirdness

- **WPT probe queue is backed up** — try 30 min later. Beijing/Shanghai queues spike during APAC business hours.
- **Lighthouse score looks crazy (e.g. 0 for everything)** — probe likely hit a 5xx or a TLS error during the run. Check the HAR before trusting the numbers.
- **Different # of requests across runs** — usually retries or CORS preflight variance. Take the median or note the variance.
- **CN probe TLS-handshakes are slower than expected** — that's the GFW. It's the point of running from CN. The numbers are valid.
