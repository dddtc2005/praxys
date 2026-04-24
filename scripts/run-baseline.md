# Running a Performance Baseline

Step-by-step for capturing a before/after snapshot using WebPageTest. The **Tier 1 matrix** (defined in `docs/perf-baselines/README.md#test-matrix-tiers`) is **4 probes × 2 devices × 4 scenarios = 32 cells**, 3 runs per cell → **~90–150 minutes** of wall clock time, most of it WPT queue wait (CN probes at 20:00 Asia/Shanghai routinely run 5–10 min per submission).

Tier 2 / Tier 3 runs (WeChat X5, Safari, tablet viewport, throttled 3G, etc.) are separate protocols — see the "Tier 2 specifics" section at the bottom.

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

Run all probes in the same calendar hour, **every baseline**. Recommended slot: **20:00–21:00 Asia/Shanghai** (Beijing evening peak — GFW is at its worst, so your numbers reflect the pessimistic real-user case). Don't split desktop across 20:00 and mobile across 21:00 — that's how you end up attributing a GFW burst to a "fix."

## The four scenarios

Definitions live in `docs/perf-baselines/README.md`. Quick recap:
- **S1** — Cold Today page (fresh profile, logged out → login → Today paint)
- **S2** — Cold Training page (fresh profile, logged out → login → Training paint)
- **S3** — Warm Today page (logged in, cache warm, tab revisit)
- **S4** — Anonymous Landing page (logged out, navigate to `/`, no login)

## Desktop vs Mobile settings (run each scenario twice)

Both form factors are Tier 1. Same WPT script, different run-level options. Keep the location string identical across the desktop/mobile pair from the same probe so the only variable is the device.

### Desktop (1920×1080 Chrome)

| WPT option | Value |
|---|---|
| Location | the Tier 1 probe (Beijing / Shanghai / HongKong / ec2-us-west-1) |
| Browser | `Chrome` |
| Connection | **Native Connection** (do NOT throttle — we want the probe's real network) |
| Mobile | **off** (no emulation) |
| Viewport | default (1920×1080 — WPT desktop default) |
| Number of runs | 3 |
| Capture Video / HAR / Lighthouse | on / on / on |

### Mobile (iPhone-class Chrome on Android emulation)

| WPT option | Value |
|---|---|
| Location | same as desktop pair |
| Browser | `Chrome` |
| Connection | **Native Connection** (explicitly override WPT's default mobile throttle — we want real CN-mobile reality, not WPT's fixed "Mobile 4G" profile of 1.6 Mbps / 150 ms) |
| Mobile | check **"Emulate Mobile Browser"** |
| Device | iPhone 14 (or the latest iPhone profile in the WPT device dropdown — WPT pulls the list from Chrome DevTools) |
| Number of runs | 3 |
| Capture Video / HAR / Lighthouse | on / on / on |

The Mobile/Native combination is deliberate: it gives us a real-world answer to "what does a CN user on their phone actually see," not the lab-ideal "what would a CN user on a fixed-profile 4G see." If you want the throttled-4G stress view, that lives in Tier 2.

## Script per scenario (WebPageTest UI)

Use **Scripted** test mode for S1 / S2 (to chain login + navigate). S3 uses **Repeat View** of the S1 script. S4 is a plain **URL test** (no script needed).

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

### S2 script

Same as S1 but replace the final navigate with `navigate https://<your-production-domain>/training`.

### S3 script

Use WPT's **"Repeat View"** feature on the S1 script — it re-runs the test with cache populated from the first-view. Capture the Repeat View metrics row only. Once Phase 2 #7 (PWA) lands, S3 is where the service-worker win shows up most clearly — expect the sharpest desktop vs. mobile divergence here because mobile devices have tighter SW cache quotas.

### S4 (no script — plain URL test)

URL: `https://<your-production-domain>/`
Runs: 3
Settings: identical to S1, minus the script (it's a single-page load with no login). Font CSS TTFB is the critical cell in S4.

## What to save per run

Create `docs/perf-baselines/<YYYY-MM-DD>-<short-sha>/` first. Then for each cell (scenario × probe × device — 32 total for Tier 1):

- **HAR file:** WPT result page → "Export HAR" → save as `s1-beijing-desktop.har`
- **Lighthouse JSON:** WPT result page → "Lighthouse" tab → download JSON → save as `s1-beijing-desktop.lighthouse.json`
- **Filmstrip:** WPT result page → "Filmstrip View" → right-click save the composite image → save as `s1-beijing-desktop.filmstrip.png`
- **WPT permalink:** copy the `https://www.webpagetest.org/result/...` URL → save as plain text in `s1-beijing-desktop.wpt-link`

Naming is strict: `s<1-4>-<probe>-<desktop|mobile>.<ext>`. If you hand-name one artifact differently, the diff script later won't line up desktop-vs-mobile deltas automatically.

## Filling in TEMPLATE.md

1. `cp docs/perf-baselines/TEMPLATE.md docs/perf-baselines/<YYYY-MM-DD>-<sha>/README.md`
2. Fill the environment fingerprint from the current deploy state.
3. For each cell (probe × device × scenario), read values from the Lighthouse JSON and the HAR:
   - **FCP / LCP / TTI / HTML TTFB** — Lighthouse JSON → `audits.metrics.details.items[0]`
   - **Static KB / API KB** — HAR → sum `response.content.size` where `request.url` matches domain vs `/api/*`
   - **# reqs / # API reqs** — HAR → count entries, split on `/api/*`
   - **API p50 / p95** — HAR → for entries matching `/api/*`, compute percentiles of `timings.wait + timings.receive`
   - **Protocol** — HAR → `_securityState` or `response.httpVersion` (look for `h2` / `h3`)
   - **Font CSS TTFB** — HAR → row for `fonts.googleapis.com/css2?...` → `timings.wait` (if timeout, write `timeout`)
4. Note observations + flaky cells at the bottom. Desktop vs mobile divergence is worth calling out explicitly when it happens.
5. Update `docs/perf-baselines/summary.md` with a one-row-per-phase rollup (create if missing).

## Commit convention

Each baseline lands in its own commit — not bundled with the code PR it measures. The code PR description links to the baseline commit for the "after" numbers.

Commit subject: `Perf baseline: <reason>` — e.g. `Perf baseline: anchor before optimization` or `Perf baseline: after Phase 1 #1 (self-host fonts)`.

## If you hit weirdness

- **WPT probe queue is backed up** — try 30 min later. Beijing/Shanghai queues spike during APAC business hours.
- **Lighthouse score looks crazy (e.g. 0 for everything)** — probe likely hit a 5xx or a TLS error during the run. Check the HAR before trusting the numbers.
- **Different # of requests across runs** — usually retries or CORS preflight variance. Take the median or note the variance.
- **CN probe TLS-handshakes are slower than expected** — that's the GFW. It's the point of running from CN. The numbers are valid.
- **Mobile emulation LCP is higher than desktop from the same probe** — expected. Smaller viewport = different "largest element," CPU throttle on mobile emulation, slower paint. The gap itself is the signal — if the gap *widens* after a fix, something went wrong.

## Tier 2 specifics (when you run them)

These aren't part of the standard Tier 1 loop. Run them periodically (every 2–4 baselines) or before a release.

### WeChat embedded browser (X5) — Beijing + Shanghai

WPT doesn't offer X5. Workflow:
1. Provision an Alibaba Cloud ECS in Beijing (smallest burstable tier; ~¥0.5/hr) with Android-x86 or Genymotion.
2. Install WeChat on the emulator; log in with a throwaway account.
3. Share the production URL into a personal WeChat chat (to yourself), tap the link to open it in WeChat's embedded browser.
4. Capture via Chrome DevTools remote debugging against the X5 rendering engine — HAR + performance trace.
5. Save as `tier2-wechat-s4-beijing.har` etc.

### Safari (iOS emulation) — 2 probes

In WPT, select Browser: `Safari` + Mobile emulation on. Available from `Dulles:Safari` historically; availability varies — check getLocations.php. If no Safari from your chosen CN probes, run from Dulles as a WebKit-behavior control and accept that it won't capture GFW effects.

### Tablet viewport — 1 probe

Any probe. In WPT "Emulate Mobile Browser" field, pick "iPad" or similar. Run S1 and S4 only.

### Throttled 3G from Hong Kong

HK + **Slow 3G** connection profile (400 Kbps / 400 Kbps / 400 ms RTT). HK isolates payload-size effects from GFW noise so you can see if Phase 1 #2 (code splitting) actually helps slow connections. Run S1 + S2 only.
