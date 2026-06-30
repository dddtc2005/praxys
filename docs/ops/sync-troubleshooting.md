# Sync troubleshooting

> **Summary:** Diagnose and recover stuck platform syncs (Garmin / Stryd / Oura).
> **Use when:** A user's dashboard data stops updating, or a connection card shows
> `auth_required`.

Domain detail lives in [`docs/dev/gotchas.md`](../dev/gotchas.md) → "Garmin sync";
this is the operational quick-path.

## #1 cause: the Garmin auth gate (`auth_required`)

By far the most common incident. Garmin/Cloudflare bot-detection trips the
headless login; the connection goes to the **`auth_required`** terminal state and
the scheduler stops retrying that user (by design — PR #256). **Do not "fix" it
with code or retries** — every fresh attempt from the App Service IP feeds the
bot score and keeps the gate hot.

**Confirm it's this:**
```kql
AppTraces | where timestamp > ago(24h)
  | where Message has "All login strategies exhausted" or Message has "IP rate limited by Garmin"
```
Or run `python scripts/garmin_diagnose.py login` — non-JSON HTML with
`challenges.cloudflare.com` = the same gate.

**Recovery (what to tell the user):**
1. Sign in at `connect.garmin.com` in a real desktop browser, complete any CAPTCHA
   (clears the account-level flag).
2. **Wait** — the per-(IP, account) gate decays on its own over hours to a day or
   two **as long as the scheduler stays parked** (it does in `auth_required`).
3. Click **Reconnect** in Praxys Settings. Success clears the backoff and the
   scheduler resumes; if it still fails, wait another half-day and retry.

Do **not** build an interactive CAPTCHA relay — Cloudflare keys on TLS
fingerprint/account history, not JS signals (closed PR #257).

## Garmin CN quirks

- `garmin.com` ≠ `garmin.cn` — separate accounts; region is captured at connect.
  To change region the user disconnects + reconnects with the other account.
- Individual CN endpoints 400/404 even on healthy accounts (LTHR, some training
  status). Each endpoint has its own try/except + a 5-strike circuit breaker, so
  one failure doesn't sink the sync. LTHR may need manual entry.

## Per-user token store (security-critical)

Tokens live at `sync/.garmin_tokens/<user_id>/`. This per-user isolation is
load-bearing — `garminconnect` loads whatever tokens it finds without validating
the account, so a shared dir would cross-leak sessions. `clear_garmin_tokens()`
runs on rotate/disconnect/delete and must propagate `OSError`. **Never** share or
relocate this store.

## Reading sync health

All per-source failures log at `warning`+ (debug once hid CN failures for months).
Aggregate warnings fire at ≥ max(3, total/2) failures; HRV/sleep circuit-break
after 5 consecutive. Check `az webapp log tail -n trainsight-app -g rg-trainsight`.

## Verify

After recovery: trigger a sync (Settings → Sync, or `POST /api/sync`), confirm the
connection card leaves `auth_required` and new activities/recovery rows appear.

## Related

- [incident-response.md](./incident-response.md) · `docs/dev/gotchas.md` · `scripts/garmin_diagnose.py`

---
_Last reviewed: 2026-06-30 · Owner: @dddtc2005_
