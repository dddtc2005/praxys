# Domain Gotchas

Non-obvious traps this codebase has hit in production. The severe, always-relevant ones (split-level power dilution, per-user tokenstore isolation) live inline in `CLAUDE.md`; the rest are here so Claude and future contributors can pull them in when working on the relevant subsystem.

## Garmin sync

### Garmin International and Garmin China are separate accounts

`garmin.com` and `garmin.cn` are different SSO domains with different account tables. A user cannot simply "switch region" — the credentials that work on one don't authenticate on the other. `is_cn` is captured at connect time and lives inside the encrypted credentials blob *and* mirrored in `user_config.source_options.garmin_region`.

- Sync reads region from `source_options.garmin_region` first (what the UI writes), falling back to `creds.is_cn` for legacy connections that predate the toggle.
- The Settings page shows region read-only. To change region, the user disconnects and reconnects with the other account's credentials.
- If these two values drift (old bug: an editable region toggle in Settings updated `source_options` but not `is_cn`), the sync client hits the wrong SSO domain and Garmin rate-limits the account with 429s.

### ConnectIQ field 10 is Stryd's convention, not a standard

Garmin lap DTOs expose a `connectIQMeasurement` array. Each entry has `developerFieldNumber`, `developerFieldName`, and `value`. **Field number 10 is Stryd's convention for power** — but any CIQ app can register a field with number 10 for anything (e.g., Leg Spring Stiffness). `parse_splits` in `sync/garmin_sync.py` checks `developerFieldName` before accepting a field-10 value as power.

Priority order in `parse_splits`:
1. Native `lap.averagePower` — present on modern Garmin watches (Fenix 6+, FR 255+/955+/965, Epix) and when HRM-Pro / Stryd pod is paired via ANT+.
2. ConnectIQ field 10 with a name that contains "power" (or no name — Stryd's historical payload).
3. Otherwise empty.

Same priority applies to activity-level `averagePower` / `maxPower` in `parse_activities`.

### Garmin CN still needs one workaround in the 0.3.x library

`garminconnect` 0.3.x had two separate CN blind spots. The DI Bearer token one was fixed upstream in 0.3.4 (PR #360 — `_di_token_url` is now a domain-aware instance attribute, so token issue + refresh route to `diauth.garmin.cn` for `is_cn=True` accounts). The mobile/widget JWT_WEB cookie bug is still live in 0.3.x and is what `_login_garmin_with_cn_fallback` in `api/routes/sync.py` papers over.

**Mobile and widget strategies consume the CAS ticket on `.com` hosts.** Strategies 1-3 hardcode `mobile.integration.garmin.com/gcm/ios` / `sso.garmin.com/sso/embed` in `_establish_session`'s JWT_WEB fallback. For CN those hosts either don't resolve or never set a JWT_WEB cookie, so the library raises `GarminConnectAuthenticationError("JWT_WEB cookie not set after ticket consumption")`. Because that's an auth error the chain re-raises immediately, never reaching the portal strategies (which use the domain-aware `_portal_service_url = "connect.garmin.cn/app"`). We catch that specific message and retry `Client._portal_web_login_cffi` directly; the message match keeps real credential failures (`"Invalid Username or Password"`) bubbling up.

With this fallback in place, CN portal login produces real DI Bearer tokens that `connectapi.garmin.cn` accepts, and `Client.dump(token_dir)` persists them so subsequent syncs skip SSO. Reproduction + verification tooling lives in `scripts/garmin_diagnose.py` — subcommands `login` (five-strategy chain, instrumented), `api` (post-login endpoint / header variants), `grants` (credential-free grant_type sweep against `diauth.garmin.cn`), `all`. GitHub issue #75.

### Garmin CN endpoint parity is incomplete

Expect individual endpoints to 400/404 on `connectapi.garmin.cn` even when the account is healthy. Confirmed patchy endpoints as of 2026-04:

- `get_lactate_threshold` — may 404; LTHR may need manual entry in Settings.
- `get_activities_by_date` with `activitytype=strength_training` — 400.
- Some `get_training_status` shapes differ.
- HRV / sleep can return `{"hrvSummary": null}` / `{"dailySleepDTO": null}` on days the watch collected nothing.

`_sync_garmin` mitigations:
- Each endpoint is in its own try/except logging at `warning` — one failure doesn't hide the rest.
- The recovery loop has per-endpoint consecutive-failure circuit breakers (5 strikes → stop calling that endpoint for the remaining days).
- `parse_garmin_recovery` uses `isinstance` guards + `or`-coalesce on every nested `.get()` — `dict.get(k, default)` returns `None`, not the default, for a present-but-null key, and the legacy code's crash here used to abort the whole recovery loop.

### Garmin's CAPTCHA gate is time-bound, not sticky

When the headless `garminconnect` flow trips Garmin/Cloudflare's bot detection, the rejection looks **permanent** but isn't. The trap is assuming you need to engineer your way around the gate when you actually just need to stop feeding it.

**The failure shape.** A stuck connection's last error is a `GarminConnectConnectionError` carrying `responseStatus.type: "CAPTCHA_REQUIRED"` (when Garmin's app layer fires the gate) or `Portal login failed (non-JSON): HTTP 403` with HTML body containing `challenges.cloudflare.com` (when Cloudflare's WAF fires it before the request reaches Garmin's auth backend). Both surface the same way to users: dashboard data stops updating; the connection card shows `auth_required`.

**The escalation that keeps the gate alive.** Every fresh SSO attempt from our App Service IP feeds the bot score. Without backoff, the scheduler retries every 10 min, the score never decays, and the gate stays hot indefinitely. This was the entire 2026-04-25 lockout — four users stuck for seven straight days because each scheduler tick fed the system that was rejecting them.

**What actually clears it.** Stop the storm. PR #256's `_record_sync_failure` + `auth_required` terminal state is the load-bearing fix: once the scheduler stops retrying, Garmin/Cloudflare's bot scoring decays naturally over **hours to a day or two**. After that the regular headless flow works again on the same IP, same account, no code changes. Confirmed empirically with the affected users from the 2026-04-25 lockout.

**What does NOT clear it (do not waste time on these).**

- An interactive Playwright viewport relay so the user solves CAPTCHA in our IP context. Built and tested locally for ~4h before this conclusion. Cloudflare returns the "Just a moment…" challenge HTML on `/portal/api/login` regardless of headless-fingerprint patches (`navigator.webdriver`, `plugins`, WebGL renderer, etc.); the patches buy nothing because Cloudflare's challenge is keyed on TLS fingerprint, header order, and account history, not just JS-detectable signals. Closed PR #257 with this rationale; the worktree-only code is not in tree.
- Switching to `camoufox` (Firefox-based stealth) is the next plausible escalation if interactive ever does become necessary, but the bar for needing it is high — it requires a stealth-vs-Cloudflare maintenance commitment we don't otherwise have.

**User-facing recovery flow** (what to tell people in the `auth_required` state):

1. Open `connect.garmin.com` in a real desktop browser, sign in successfully, complete any CAPTCHA shown. This clears any **account-level** flag the storm raised.
2. Wait — overnight is usually enough; same-day works often. The gate is per-(IP, account) and decays without our intervention as long as the scheduler stays parked.
3. Click **Reconnect** in Praxys Settings. The headless flow runs again; if it succeeds, `_upsert_connection_credentials` clears the backoff state and the scheduler resumes. If it still fails, wait another half-day and retry.

The diagnostic to confirm a future "is this the same gate" is `scripts/garmin_diagnose.py login` — captured non-JSON HTML response with `challenges.cloudflare.com` references = same family. App Insights query `AppTraces | where Message has "All login strategies exhausted" or Message has "IP rate limited by Garmin"` shows the same pattern at the fleet level.

### Recovery RHR vs TRIMP threshold RHR

Two different RHR values for two different purposes:

- `recovery_data.resting_hr` — per-day overnight RHR from sleep data. Drives the HRV / recovery chart. Varies with sleep quality.
- `fitness_data.rest_hr_bpm` — configured profile RHR from `get_user_profile()`. Stable. Used as the TRIMP `rest_hr` threshold input.

Don't cross-wire them: overnight RHR as the TRIMP threshold would inject daily noise into every workout's load calculation.

### Running power: Garmin native vs Stryd are not interchangeable

Garmin exposes a running FTP (their "Critical Power" for running) at
`/biometric-service/biometric/latestFunctionalThresholdPower/RUNNING`
— the same URL pattern garminconnect wraps as `get_cycling_ftp()` but
for `RUNNING`. We sync that into `fitness_data.cp_estimate` (source
`garmin`). Observed gap vs Stryd on the same athlete: **~30% higher on
Garmin** (e.g. Garmin 350W vs Stryd 265W).

Why they differ:

- **Stryd** is a foot-mounted pod (3-axis accelerometer + gyroscope +
  barometer) measuring foot-strike mechanics directly. It's been
  research-validated against treadmill mechanical power; outputs scale
  close to mechanical work on the runner.
- **Garmin native running power** is a model-based estimate from
  wrist / HRM-Pro accelerometer + pace + gradient. It rolls in
  metabolic cost estimates, so the numbers are higher than raw
  mechanical work and run noticeably different on hills.

Neither is "wrong", but **zones calibrated on one don't transfer**.
Most published training literature and coach references are calibrated
on Stryd. When a user has both sources connected, the resolver picks
between them using the threshold-source-selection rules below.

The Settings → Training Base UI shows a cobalt-bordered note when the
user picks Power without Stryd connected, so the user knows the
numbers aren't directly comparable to Stryd-calibrated references.

## Threshold resolution

`_resolve_thresholds` in `api/deps.py` never accepts arbitrary user-entered
numeric values — every threshold traces back to a connected source or a
calculation we run on the user's own data. Manual numeric overrides were
removed from the schema; the `thresholds` field in `PUT /api/settings`
bodies is accepted for API compat but silently discarded (with an INFO log
so stragglers are findable).

Selection order for each threshold (`cp_watts`, `lthr_bpm`,
`threshold_pace_sec_km`, `max_hr_bpm`, `rest_hr_bpm`):

1. **Explicit** — `preferences.threshold_sources[metric_type]` if that
   source has any rows for that metric.
2. **Default** — `preferences.activities` (the primary activity source).
   Keeps CP aligned with the activities the user is viewing.
3. **Fallback** — latest `fitness_data` row by date, regardless of source.
   When the preferred source has no data the resolver falls back here and
   emits a DEBUG log so the "why am I seeing Garmin's value when I picked
   Stryd?" case is traceable.

Special case for `max_hr_bpm`: if `fitness_data` has no `max_hr_bpm` row
at all, the resolver derives it from `max(Activity.max_hr)`. This is a
calculation on the user's own data (not a guess), so it fits the
"connected source or calculated by us" rule. Without this, HR-base users
with Garmin-only sync had `max_hr_bpm = None` → TRIMP returned `None` →
every daily load was 0 → empty fitness/fatigue chart.

The UI in Settings renders a read-only value plus a source selector
(populated from `options[]` on the `GET /api/settings` response) when a
metric has more than one source. Single-source or zero-source metrics
render read-only with a source badge.

### Tokenstore lifecycle

- First sync: no tokens present → `has_tokens = False` → `client.login(None)` uses credentials flow → `garth.dump(token_dir)` writes `oauth1_token.json` + `oauth2_token.json`.
- Subsequent syncs: files exist → `has_tokens = True` → `client.login(token_dir)` loads cached tokens, skips SSO.
- `clear_garmin_tokens(user_id)` is called on credential rotation / disconnect / user deletion. It must propagate OSError — silencing it would re-open the cross-user leak the per-user path exists to prevent.

## Backfill semantics

- `write_activities` / `write_splits` are **fill-only upserts** for a whitelisted set of columns (`avg_power`, `max_power`). If a row already exists and a column is NULL, a re-sync fills it; non-null values are preserved verbatim. This lets users benefit from parser improvements (e.g. native Garmin power) without deleting their existing data, *and* protects against clobbering Stryd-sourced power with a different Garmin reading in dual-sync scenarios.
- `write_lactate_threshold` and `write_daily_metrics` are insert-only (existing rows skipped) — they're time-series of fresh values, so per-date idempotency is the right semantics.
- Recovery (`recovery_data`) is update-capable per date (see `write_recovery`'s Garmin branch) so a partial first-sync row can be topped up on a later sync that returns HRV where the first didn't.

## Sync status observability

All per-source sync errors surface at `logger.warning` or above, not `debug`. Debug-level was the pattern that silently hid real failures on Garmin CN for months. Per-day failures inside loops (HRV, sleep) still log at `debug`, but counters aggregate into a single `warning` when a meaningful fraction fail:

- Splits: warning when ≥ max(3, total/2) activities fail.
- Recovery parse: warning when ≥ max(3, total/2) days fail.
- HRV / sleep endpoints: circuit-break + warning after 5 consecutive failures.
