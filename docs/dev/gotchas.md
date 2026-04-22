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

### Recovery RHR vs TRIMP threshold RHR

Two different RHR values for two different purposes:

- `recovery_data.resting_hr` — per-day overnight RHR from sleep data. Drives the HRV / recovery chart. Varies with sleep quality.
- `fitness_data.rest_hr_bpm` — configured profile RHR from `get_user_profile()`. Stable. Used as the TRIMP `rest_hr` threshold input.

Don't cross-wire them: overnight RHR as the TRIMP threshold would inject daily noise into every workout's load calculation.

### Max HR resolution

`_resolve_thresholds` in `api/deps.py` resolves `max_hr_bpm` in this order:

1. `config.thresholds.max_hr_bpm` (manual user override in Settings).
2. `fitness_data.max_hr_bpm` row for this user (written by `write_profile_thresholds` from Garmin user profile).
3. `max(Activity.max_hr)` across the user's activities — last-resort fallback for users with no profile value.

Without #3, HR-base users with Garmin-only sync had `thresholds.max_hr_bpm = None` → TRIMP returned `None` → every daily load was 0 → empty fitness/fatigue chart.

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
