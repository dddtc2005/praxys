# Webhook Feasibility Study: Oura and Garmin

Trainsight currently syncs Oura and Garmin data via scheduled polling (see `db/sync_scheduler.py`). This study asks whether event-driven webhooks could replace or augment that polling.

## TL;DR

- **Oura**: Webhooks exist (`/v2/webhook/subscription`) and are feasible, but the migration cost is high (OAuth2 migration, public HTTPS endpoint, subscription-renewal job, new DB table). For single-user and small self-hosted deployments, the polling scheduler hardened in this PR already delivers acceptable latency (6-24h, configurable). **Recommendation: keep polling. Revisit only if we need sub-hour latency, gain a multi-user deployment, or migrate to OAuth2 for unrelated reasons.**
- **Garmin**: Official Health API Ping/Push webhooks are restricted to approved business developers per Garmin's Connect Developer Program FAQ. Not available to hobby or self-hosted projects. No viable community workaround exists -- every open-source alternative ultimately polls. **Recommendation: not pursuable; tracked as an open study task to re-check annually.**

## Current state: how sync works today

Polling is driven by a background thread started on app boot:

- `db/sync_scheduler.py` -- daemon thread, checks every 10 minutes (after a 30s startup delay), respects per-user `sync_interval_hours` (6/12/24h; validated via `normalize_sync_interval_hours()`)
- `sync/oura_sync.py` -- calls `GET https://api.ouraring.com/v2/usercollection/sleep` and `/daily_readiness`, authenticated with a Personal Access Token
- `db/sync_writer.py` `write_recovery()` -- upserts into `recovery_data` keyed on `(user_id, date, source)`
- `api/routes/sync.py` -- exposes `POST /api/sync` and `POST /api/sync/{source}` for manual triggers; decrypts credentials via `db/crypto.py` Fernet envelope

Credentials are stored encrypted in `user_connections.encrypted_credentials`. There is no inbound webhook listener anywhere in the codebase today, and no HMAC verification helper to reuse.

## Oura webhooks: what the API offers

Based on the official API surface at `https://cloud.ouraring.com/v2/docs#tag/Webhook-Subscription-Routes` (docs page is a SPA and is best viewed in a browser).

> All claims in this section are sourced from Oura's external documentation, not from Trainsight code -- no webhook receiver exists in this codebase yet. Re-verify against the live Oura docs before any implementation.

**Subscription management endpoints** (all under `https://api.ouraring.com`):

| Method | Path | Purpose |
|---|---|---|
| `PUT` | `/v2/webhook/subscription` | Create a subscription |
| `GET` | `/v2/webhook/subscription` | List subscriptions |
| `GET` | `/v2/webhook/subscription/{id}` | Fetch one subscription |
| `PUT` | `/v2/webhook/subscription/renew/{id}` | Renew (resets TTL) |
| `DELETE` | `/v2/webhook/subscription/{id}` | Delete a subscription |

**Supported `data_type` values**: `tag`, `enhanced_tag`, `workout`, `session`, `sleep`, `daily_sleep`, `daily_readiness`, `daily_activity`, `daily_spo2`, `sleep_time`, `rest_mode_period`, `ring_configuration`, `daily_stress`, `daily_cardiovascular_age`, `daily_resilience`, `vO2_max`, `heartrate`.

**Supported `event_type` values**: `create`, `update`, `delete`.

**Subscription lifecycle**:

- Subscriptions expire in roughly 90 days and must be renewed via the `renew` endpoint. If a subscription is not renewed, Oura stops delivering events for it.
- On subscription creation, Oura performs a verification challenge against the callback URL. The server must respond correctly before the subscription is activated.
- The callback URL must be HTTPS with a valid, publicly verifiable certificate chain.

**Authentication / signing**:

- Creating subscriptions requires the app's OAuth2 client credentials (`x-client-id` and `x-client-secret` headers) -- not the end-user's access token.
- Subscribing to user-scoped data requires the user to have authorized the OAuth2 app with appropriate scopes.
- The event payload delivered to the callback URL includes an object reference (data type + object id + user id) rather than the full record. The server still has to call the Oura API to fetch the actual data. This means event delivery saves latency, but does not reduce per-record API calls.

## What adopting Oura webhooks would require

1. **OAuth2 migration for Oura** -- today `sync/oura_sync.py` uses a Personal Access Token pasted into the Settings UI. Webhook subscriptions are a per-app, not per-PAT, feature. This forces an OAuth2 client setup, a redirect flow, token storage changes in `db/models.py` `UserConnection`, and refresh-token handling. This is the largest cost of adoption and is valuable independently, but has to be built either way.
2. **New `WebhookSubscription` table** (`db/models.py`) with columns: `user_id`, `source`, `external_id` (Oura's id), `data_type`, `expires_at`, and (if Oura HMAC-signs payloads) a shared secret. Unique on `(user_id, source, data_type)`.
3. **Public inbound routes** in a new `api/routes/webhooks.py`:
   - `POST /webhooks/oura` -- verify signature/origin, enqueue a targeted fetch of the referenced object, upsert via existing `db/sync_writer.py` helpers.
   - `GET /webhooks/oura/verify` (or equivalent) -- handle the Oura verification challenge on subscription creation.
   - Rate limiting and idempotency (events can be redelivered).
4. **Scheduler repurposing** -- `db/sync_scheduler.py` would shift from "poll all users every N hours" to:
   - renew any `WebhookSubscription` with `expires_at < now + 7 days`;
   - run a weekly fallback full-pull per user as belt-and-braces in case events were missed.
5. **Deployment requirements** -- public HTTPS endpoint with a valid cert chain. Self-hosters without a public domain would need ngrok / Cloudflare Tunnel / similar, documented in `README.md` and `.env.example`. Purely-LAN deployments would have to stay on polling.
6. **Observability** -- a "last webhook received" field per subscription and an admin surface to see whether events are flowing. Without this, webhook silence is indistinguishable from "nothing happened."

## Cost / benefit

| Dimension | Polling (today) | Webhooks |
|---|---|---|
| Data latency | 6-24h (configurable) | Seconds, bounded by our processing |
| Code/arch complexity | Low: one scheduler loop | High: OAuth, public routes, subscription table, renewal job, signature verification, fallback poll |
| Self-hoster setup | PAT paste in Settings | Public HTTPS URL + OAuth2 client creation on Oura's portal |
| Operational burden | Credentials rotation only | Subscription-renewal failures, event-delivery failures, signature mismatches, TLS-chain issues |
| API usage | Steady low volume | Spikier but similar total (events still reference-only, must fetch) |
| Failure mode | Sync lags by one interval | Subscription expires silently, data stops arriving until we notice |

Webhooks clearly win on latency. Every other dimension favours polling until we have a concrete reason to need near-real-time data.

## Recommendation

**Keep polling. Do not implement Oura webhooks yet.** Revisit when any of these triggers fire:

- We already need to migrate Oura auth to OAuth2 for another reason (API changes, per-user scoping, etc.) -- the marginal cost of adding webhooks then is much smaller.
- We grow past a handful of active users, at which point polling every user every 6h becomes observably wasteful.
- A concrete feature (e.g. live "as soon as you wake up" brief) needs latency the polling scheduler cannot deliver.
- Oura changes policy to require webhooks (unlikely in the near term).

In the meantime, the scheduling hardening in this PR (`normalize_sync_interval_hours()`, guarded per-user intervals, Settings UI control) is the right investment.

## Garmin webhooks

Officially, the [Garmin Connect Developer Program](https://developer.garmin.com/gc-developer-program/) exposes both Ping (notify + pull) and Push (notify with payload) webhook architectures via the Health API. The API covers dailies, sleep, stress, pulse-ox, respiration, body composition, and activity summaries; authentication is OAuth 2.0 with PKCE; callbacks must return HTTP 200 within 3 seconds, so any real work has to be queued and handled asynchronously.

**However**: per the Connect Developer Program FAQ, access is restricted to approved business developers. Individual / hobbyist / self-hosted use is explicitly out of scope, and there is no paid self-serve tier. The Training API is write-only (upload plans to devices), so it does not help with ingest.

Community projects (e.g. `cyberjunky/home-assistant-garmin_connect`) all poll via unofficial Garmin Connect endpoints; there is no community-built webhook bridge, and attempts using Connect IQ apps to push from-device have not produced a shared reusable solution.

**Recommendation**: not pursuable today. The useful move is to re-check the program's policy periodically and to keep polling via the unofficial API robust.

### Open study: Garmin webhook feasibility

Tracked follow-up items (no file moved or created -- kept inline here to avoid doc sprawl):

- [ ] Re-check annually whether Garmin opens the Health API to non-commercial developers or adds a paid self-serve tier.
- [ ] Evaluate a Connect IQ companion app as a device-side bridge (ConnectIQ → user-controlled HTTP endpoint). Assess what data is actually accessible from the device context.
- [ ] Evaluate using an intermediary that already has Garmin approval and exposes outbound webhooks (e.g. Intervals.icu, Strava) as a broker -- effectively buying real-time without the approval.
- [ ] Reopen the decision if Trainsight ever gains a commercial entity eligible to apply to the Health API program.

## References

- Oura API docs: <https://cloud.ouraring.com/v2/docs>
- Oura developer portal: <https://cloud.ouraring.com/>
- Garmin Connect Developer Program: <https://developer.garmin.com/gc-developer-program/>
- Garmin Health API: <https://developer.garmin.com/gc-developer-program/health-api/>
- Garmin Connect Developer Program FAQ: <https://developer.garmin.com/gc-developer-program/program-faq/>
- HomeAssistant Garmin integration (polling reference): <https://github.com/cyberjunky/home-assistant-garmin_connect>
