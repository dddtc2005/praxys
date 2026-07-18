# API Reference

All endpoints are under the `/api/` prefix. The API server runs on `http://localhost:8000` by default.

**Authentication:** All data endpoints require `Authorization: Bearer <token>` in the request header. Tokens are obtained via `POST /api/auth/login`.

## Auth

### POST /api/auth/register

Register a new user.

- **First user** on a fresh DB becomes admin (no code, auto-verified).
- Email matching `PRAXYS_ADMIN_EMAIL` → admin (no code, auto-verified).
- A valid **invitation code** → normal user (auto-verified; invited users bypass the seat cap).
- **Open self-registration** (admin-enabled gate, under the committed-seat cap, no code) →
  created *unverified*; a verification link is emailed and the user cannot log in until they
  click it (see `POST /api/auth/verify`). If SMTP is not configured, the account is created
  verified instead.

**Request body:**
```json
{
  "email": "user@example.com",
  "password": "securepassword",
  "invitation_code": "TS-ABCD-1234",
  "accepted_terms": true,
  "website": ""
}
```

- `invitation_code` — optional; omit for the first user, `PRAXYS_ADMIN_EMAIL`, or an open sign-up.
- `accepted_terms` — **required** (`true`); the EULA gate.
- `website` — **honeypot**; must be empty. A non-empty value is treated as a bot and rejected.

**Response** (verified path — first user / admin email / invited):
```json
{ "id": "uuid-string", "email": "user@example.com", "is_superuser": false }
```

**Response** (open sign-up needing email verification):
```json
{ "verification_required": true, "email": "user@example.com" }
```

**Error codes:**
- `400 REGISTER_USER_ALREADY_EXISTS` — email already registered
- `400 REGISTER_TERMS_NOT_ACCEPTED` — `accepted_terms` was not `true`
- `400 REGISTER_INVALID_INVITATION` — code is invalid, used, expired, or revoked
- `400 REGISTER_FAILED` — honeypot tripped (or an opaque create failure)
- `403 REGISTER_CLOSED` — self-registration is disabled or the seat cap is reached

### POST /api/auth/login

Obtain a JWT access token. Uses FastAPI-Users auth backend.

**Request body** (form-encoded):
```
username=user@example.com&password=securepassword
```

**Response:**
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

### GET /api/auth/me

Return the authenticated user's profile.

**Response:**
```json
{
  "id": "uuid-string",
  "email": "user@example.com",
  "is_superuser": true,
  "created_at": "2026-04-01T12:00:00"
}
```

### POST /api/auth/request-verify-token

Request (or re-send) an email-ownership verification link. Always returns `202` regardless of
whether the address exists (no account enumeration); sends an email only when SMTP is configured.

**Request body:** `{ "email": "user@example.com" }`

### POST /api/auth/verify

Consume a verification token (from the emailed link `…/verify?token=…`) and mark the account
verified, unblocking login.

**Request body:** `{ "token": "<token>" }`

Errors: `400 VERIFY_USER_ALREADY_VERIFIED`, `400 VERIFY_USER_BAD_TOKEN` (FastAPI-Users).

### GET /api/public/config

**Unauthenticated.** Minimal boot config for the login page.

**Response:** `{ "registration_open": true }`

- `registration_open` — effective state (admin flag **and** committed seats < cap). No counts or
  other operator data are exposed here.

## Admin

All admin endpoints require `is_superuser=True` on the authenticated user. Returns `403` otherwise.

### GET /api/admin/ops/summary

Privacy-safe operations overview. Query parameter `window` is one of `24h`, `7d`,
or `28d` (default `24h`). Every section includes `source`, `window`, `freshness`,
`as_of`, and an optional stable `reason` code (`section_refresh_failed` or
`azure_telemetry_not_connected`).

Phase 1 returns database-backed attention/activity aggregates and live component
health. Azure alert and platform-health sections return `freshness: "unavailable"`
until #417 is complete. The response contains no emails, user IDs, feedback text,
screenshots, invitation codes, or Coach comments. One failed section does not fail
the whole response. Responses are `private, no-store`.

```json
{
  "generated_at": "2026-07-17T12:00:00+00:00",
  "window": "24h",
  "attention": {
    "source": "praxys_database", "window": "live", "freshness": "fresh",
    "as_of": "2026-07-17T12:00:00+00:00", "reason": null,
    "data": {
      "incident_counts": {"total": 1, "minor": 0, "major": 1, "critical": 0},
      "active_incidents": [{"id": 4, "title": "Elevated latency", "status": "investigating", "impact": "major", "started_at": "...", "updated_at": "..."}],
      "feedback": {"needs_review": 2, "failed": 1, "new": 3, "actionable": 3, "critical": 1, "high": 1, "total": 8}
    }
  },
  "service_health": {"source": "live_probe", "window": "live", "freshness": "fresh", "as_of": "...", "reason": null, "data": {"overall": "operational", "components": []}},
  "product_value": {"source": "praxys_database", "window": "rolling_1d_7d_30d", "freshness": "fresh", "as_of": "...", "reason": null, "data": {"registered_users": 12, "dau": 4, "wau": 9, "mau": 11, "directional": true}},
  "azure_alerts": {"source": "azure_monitor", "window": "24h", "freshness": "unavailable", "as_of": null, "reason": "azure_telemetry_not_connected", "data": null},
  "platform_health": {"source": "azure_monitor", "window": "24h", "freshness": "unavailable", "as_of": null, "reason": "azure_telemetry_not_connected", "data": null},
  "links": {"users": "/admin/users", "feedback": "/admin/feedback", "incidents": "/admin/incidents", "communications": "/admin/communications", "public_status": "/status", "monitoring_docs": "...", "telemetry_trust_issue": "..."}
}
```

### GET /api/admin/users

List all registered users.

**Response:**
```json
{
  "users": [
    {
      "id": "uuid-string",
      "email": "user@example.com",
      "is_active": true,
      "is_superuser": true,
      "created_at": "2026-04-01T12:00:00"
    }
  ]
}
```

### DELETE /api/admin/users/{id}

Delete a user and cascade-delete all their data (activities, splits, recovery, fitness, plans, connections, config). Cannot delete yourself.

**Response:**
```json
{ "status": "deleted", "email": "user@example.com" }
```

### PATCH /api/admin/users/{id}/role

Toggle admin role for a user. Cannot change your own role.

**Request body:**
```json
{ "is_superuser": true }
```

**Response:**
```json
{
  "id": "uuid-string",
  "email": "user@example.com",
  "is_superuser": true
}
```

### POST /api/admin/invitations

Generate a one-time invitation code (format: `TS-XXXX-XXXX`).

**Request body (optional):**
```json
{ "note": "For teammate Alice" }
```

**Response:**
```json
{ "code": "TS-A1B2-C3D4", "note": "For teammate Alice" }
```

### GET /api/admin/invitations

List all invitation codes with usage status.

**Response:**
```json
{
  "invitations": [
    {
      "id": 1,
      "code": "TS-A1B2-C3D4",
      "note": "For teammate Alice",
      "is_active": true,
      "created_at": "2026-04-01T12:00:00",
      "used_by": null,
      "used_at": null
    }
  ]
}
```

### DELETE /api/admin/invitations/{id}

Revoke an invitation code (cannot be used after this).

**Response:**
```json
{ "status": "revoked", "code": "TS-A1B2-C3D4" }
```

### POST /api/admin/demo-accounts

Create a read-only demo account that mirrors the creating admin's data. Demo users can browse all pages but cannot modify anything (403 on all write endpoints).

**Request:**
```json
{ "email": "demo@example.com", "password": "demo-pass" }
```

**Response:**
```json
{
  "id": "uuid",
  "email": "demo@example.com",
  "is_demo": true,
  "demo_of": "admin-user-id"
}
```

### GET /api/admin/config

Registration gate, seat cap, activity gauge, and email availability.

**Response:**
```json
{
  "registration": {
    "registration_open": true, "flag_enabled": true, "max_users": 100,
    "registered_users": 12, "outstanding_invitations": 3,
    "committed_seats": 15, "remaining": 85, "cap_reached": false
  },
  "activity": { "dau": 4, "wau": 9, "mau": 11, "total_users": 12 },
  "email_configured": true
}
```

### PATCH /api/admin/config

Toggle self-registration and/or set the seat cap. Both fields optional.

**Request:** `{ "registration_open": true, "registration_max_users": 100 }`

**Response:** same shape as `GET /api/admin/config`. `400` if `registration_max_users < 0`.

The **seat cap counts committed seats** = registered non-demo users **plus** outstanding
(active, unused, unexpired) invitation codes. Self-registration auto-closes when committed ≥ cap;
admin-issued invitations bypass it.

### GET /api/admin/waitlist

List waitlist signups (newest first), each with any issued invitation code.

**Response:**
```json
{
  "signups": [
    {
      "id": 1, "email": "lead@example.com", "note": "sub-3 marathon",
      "locale": "zh", "created_at": "2026-07-01T10:00:00+00:00",
      "invited_at": null, "invitation_id": null, "invitation_code": null
    }
  ]
}
```

### GET /api/admin/announcements

Return all system announcements, including inactive rows, for the communications
management route. Regular authenticated users continue to receive active rows only
from `GET /api/announcements`.

### POST /api/admin/waitlist/{id}/invite

Generate a 14-day invitation code for a waitlist signup, mark the row, and email the code + a
prefilled register link (when SMTP is configured). Re-inviting revokes the prior unused code.

**Response:**
```json
{
  "sent": true, "email_configured": true, "code": "TS-A1B2-C3D4",
  "email": "lead@example.com",
  "invite_url": "https://praxys.run/login?invite=TS-A1B2-C3D4",
  "expires_at": "2026-07-18T10:00:00+00:00"
}
```

## Today

### GET /api/today

Deterministic same-day training signal. `signal` is the sole authority for the
recommendation, reason, and alternatives; Today does not load or generate an
LLM `daily_brief`.

Recovery classification is HRV-based. The current HRV observation is excluded
from its own historical baseline; the default method requires seven preceding
valid observations. `rolling_days` and `baseline_days` are retained configuration
names, but they count valid observations rather than calendar days. Identical
historical observations have zero variance and therefore return
`classification_reason = "zero_variance"` instead of a normal classification.
An HRV reading from today or yesterday is current. Older HRV
is retained for provenance but sets `hrv_is_stale = true`, returns
`recovery_analysis.status = "insufficient_data"`, and cannot adjust the same-day
signal. Sleep, readiness, and resting heart rate remain available as separate
informational context when the source provides them. Recovery and plan frames use
one configured provider at a time rather than blending overlapping sources.

**Response:**
```json
{
  "as_of_date": "2026-04-08",
  "data_as_of": "2026-04-07T12:00:00Z",
  "coach_snapshot": "8f2c90a4d43818aaaf943b0f1a27c997",
  "signal": {
    "recommendation": "follow_plan|unscheduled|modify|reduce_intensity|easy|rest",
    "reason": "English fallback string",
    "reason_code": "stable_semantic_code",
    "reason_args": { "tsb": -18.2 },
    "alternatives": ["English fallback string"],
    "alternative_codes": [{ "code": "stable_semantic_code", "args": {} }],
    "recovery": { "tsb": 0.6, "hrv_ms": 59.0, "sleep_score": 82.0, "readiness": 76.0 },
    "plan": { "workout_type": "easy", "duration_min": "60", "..." : "..." }
  },
  "recovery_analysis": {
    "status": "fresh|normal|fatigued|insufficient_data",
    "hrv": { "today_ms": 59.0, "baseline_mean_ln": 3.87, "trend": "improving" },
    "sleep_score": 82.0,
    "readiness_score": 76.0,
    "resting_hr": 49.5,
    "rhr_trend": "low|stable|elevated",
    "latest_date": "2026-04-07",
    "is_stale": false,
    "hrv_latest_date": "2026-04-07",
    "hrv_is_stale": false,
    "classification_reason": "missing_hrv|insufficient_history|zero_variance|stale_hrv|null"
  },
  "last_activity": {
    "date": "2026-04-07",
    "activity_type": "running",
    "distance_km": 9.43,
    "duration_sec": 3233,
    "avg_power": 210.0,
    "avg_pace_min_km": "5:42",
    "rss": 64.8
  },
  "tsb_sparkline": { "dates": ["..."], "values": ["..."], "projected_dates": ["..."], "projected_values": ["..."] },
  "recovery_theory": { "id": "hrv_based", "name": "HRV-Based Recovery", "simple_description": "...", "params": {} },
  "upcoming": [
    { "date": "2026-04-11", "workout_type": "threshold", "duration_min": 65, "description": "..." }
  ],
  "week_load": { "week_label": "W15", "actual": 245.3, "planned": 280.0 },
  "warnings": ["HRV rolling mean declining"],
  "training_base": "power",
  "display": { "threshold_abbrev": "CP", "threshold_unit": "W", "load_label": "RSS" }
}
```

`reason` and `alternatives` are deterministic English fallbacks. Clients should
localize the stable `reason_code` / `alternative_codes` and interpolate their
argument maps without changing the recommendation. `week_load` is `null` when no
current-week activity or plan load exists; `recovery_analysis`, `last_activity`,
and `recovery_theory` are also nullable. `signal.recovery.tsb` is `null` until the
account has one active CTL time constant of history. A null TSB is excluded from
same-day decisions and clients render it as unavailable rather than as a balanced
value of zero. The one-time-constant history gate and displayed TSB labels are
Praxys product estimates, not validated physiological cutoffs.

`coach_snapshot` is an opaque cache/source version retained for response
compatibility. It is not an insight identifier and clients should not use it to
request same-day prose.

## Training

### GET /api/training

Training analysis and diagnosis.

**Response:**
```json
{
  "diagnosis": {
    "lookback_weeks": 6,
    "volume": { "weekly_avg_km": 51.6, "trend": "stable" },
    "consistency": { "total_sessions": 18, "weeks_with_gaps": 1, "longest_gap_days": 4 },
    "interval_power": {
      "max": 292,
      "avg_work": 237,
      "supra_cp_sessions": 6,
      "total_quality_sessions": 12,
      "data_available": true,
      "evidence_complete": true,
      "activities_with_intensity_data": 18,
      "activities_expected": 18
    },
    "distribution": [
      { "name": "Easy", "actual_pct": 72, "target_pct": 80 },
      { "name": "Threshold", "actual_pct": 15, "target_pct": 8 }
    ],
    "zone_ranges": [{ "name": "Easy", "lower": 0, "upper": 136, "unit": "W" }],
    "data_meta": { "distribution_resolution": "samples|splits|mixed|activity_averages|unavailable" },
    "diagnosis": [{ "type": "positive|warning|neutral", "message": "string" }],
    "suggestions": ["string"]
  },
  "fitness_fatigue": {
    "dates": ["2026-02-10", "..."],
    "ctl": [45.2, "..."],
    "atl": [52.1, "..."],
    "tsb": [-6.9, "..."],
    "projected_dates": ["..."],
    "projected_ctl": ["..."],
    "projected_tsb": ["..."]
  },
  "cp_trend": { "dates": ["..."], "values": ["..."] },
  "weekly_review": {
    "weeks": ["W10", "..."],
    "actual_load": ["..."],
    "planned_load": ["..."],
    "actual_estimated": false,
    "planned_estimated": false,
    "week_actual_estimated": [false, false],
    "week_planned_estimated": [false, true],
    "week_complete": [true, false]
  },
  "summary": {
    "current_tsb": -6.9,
    "distribution_match_pct": 83,
    "load_compliance_pct": 96
  },
  "workout_flags": [{ "date": "...", "flag": "good|bad", "reason": "..." }],
  "sleep_perf": {
    "pairs": [[85, 240.3], ["..."]],
    "metric_label": "Avg Power",
    "metric_unit": "W"
  },
  "training_base": "power",
  "display": { "..." : "..." },
  "data_meta": {
    "activity_count": 18,
    "data_days": 35,
    "cp_points": 4,
    "has_recovery": true,
    "load_time_constant_days": 42,
    "pmc_sufficient": false,
    "cp_trend_sufficient": true
  }
}
```

`summary` contains server-computed display metrics so web, miniapp, and legacy
dashboard consumers do not duplicate training formulas. `current_tsb` is `null`
until the account has one active CTL time constant of history.
`distribution_match_pct` is `null` unless every recent activity has at least 90%
duration coverage from split or timestamped sample intensity and every zone has
a target. Timestamped samples also require a median cadence of five seconds or
less. `load_compliance_pct` uses only completed weeks where both actual and
planned load have exact selected-base inputs and the plan target is positive.
It is `null` until at least two such weeks exist. A week is complete only after
Sunday has passed and daily load contains all seven Monday-through-Sunday dates.
The result is a descriptive mean actual-to-planned load ratio, not a quality,
safety, recovery, or readiness score. `week_actual_estimated` and
`week_planned_estimated` provide the per-week provenance; estimated bars remain
visible but are excluded from the summary. Durationless `rest` and `off` plan
rows are exact zero load; other durationless rows remain estimated.
`load_time_constant_days` comes from the active load theory and controls
`pmc_sufficient`. Both the one-time-constant sufficiency gate and the two-week
minimum are Praxys product estimates rather than validated physiological cutoffs.

When valid split-level intensity evidence is absent, `max`, `avg_work`,
`supra_cp_sessions`, and `total_quality_sessions` are `null`, and
`evidence_complete` is `false`. HR- and pace-based accounts may receive a coarse
`activity_averages` distribution for display, but it never qualifies for
`distribution_match_pct`. When no usable intensity exists, the distribution keeps
its stable array shape with zero placeholders and `distribution_resolution` is
`unavailable`; clients must not interpret those zeros as completed recovery-zone
time or zero quality work.

## Goal

### GET /api/goal

Race prediction and goal tracking.

**Response:**
```json
{
  "race_countdown": {
    "distance": "marathon",
    "distance_label": "Marathon",
    "mode": "race_date|cp_milestone|continuous|none",
    "current_cp": 247.8,
    "target_cp": 280.0,
    "predicted_time_sec": 13852,
    "target_time_sec": 10800,
    "cp_gap_watts": 70.0,
    "status": "on_track|close|behind|unlikely",
    "prediction_method": "critical_power|riegel|none",
    "prediction_theory": "Critical Power (Stryd Race Power)",
    "milestones": [{ "cp": 270, "marathon": "~3:50", "reached": false }],
    "reality_check": { "assessment": "...", "severity": "..." }
  },
  "cp_trend": { "dates": ["..."], "values": ["..."] },
  "cp_trend_data": { "direction": "improving|stable|falling", "slope_per_month": -3.9 },
  "latest_cp": 247.8,
  "training_base": "power",
  "display": { "..." : "..." }
}
```

> **Units.** `latest_cp`, `current_cp`, `target_cp`, `cp_trend.values` are in the user's
> base-native threshold unit (watts for power, bpm for HR, sec/km for pace).
> Pair with `display.threshold_unit` to format. `actual_load` / `planned_load`
> similarly carry RSS / TRIMP / rTSS depending on the training base; pair with
> `display.load_label`.

## History

### GET /api/history

Paginated activity history.

**Query params:**
- `limit` (int, 1-100, default 20)
- `offset` (int, default 0)

**Response:**
```json
{
  "activities": [
    {
      "date": "2026-04-07",
      "distance_km": 9.43,
      "duration_sec": 3233,
      "avg_power": 210.0,
      "avg_hr": 155,
      "avg_pace_min_km": "5:42",
      "rss": 64.8,
      "splits": [{ "split_num": 1, "avg_power": 220, "duration_sec": 300 }]
    }
  ],
  "total": 150,
  "limit": 20,
  "offset": 0,
  "training_base": "power",
  "display": { "..." : "..." }
}
```

## Plan

### GET /api/plan

The user's AI plan within a window, plus per-row Stryd sync state and the
caller's Stryd push history.

The canonical plan is the AI-authored one (`source='ai'`); Stryd plan rows
in the same window are surfaced as a `sync_state` flag on each AI row and
as `stryd_only_dates` for Stryd entries with no AI counterpart.

**Query params:**
- `start` *(YYYY-MM-DD, default = today)* — window start.
- `end` *(YYYY-MM-DD, default = `start + 14 days`)* — window end. Inverted
  or longer-than-365-day windows return 400.

**Response:**
```json
{
  "workouts": [
    {
      "date": "2026-04-11",
      "workout_type": "threshold",
      "duration_min": 65,
      "distance_km": 11.0,
      "power_min": 235,
      "power_max": 255,
      "description": "WU 10min, 2x20min @235-255W...",
      "sync_state": "synced"
    }
  ],
  "stryd_status": {
    "2026-04-11": { "workout_id": "stryd_123", "pushed_at": "...", "status": "pushed" }
  },
  "sync_target": "stryd",
  "stryd_only_dates": ["2026-04-13"],
  "window": { "start": "2026-04-11", "end": "2026-04-25" }
}
```

`sync_state` is one of:
- `synced` — Stryd has a matching workout whose id equals the one we
  logged on push (a re-push is a no-op).
- `mismatch` — Stryd has a workout on this date but we don't recognise
  its id (user-edited on Stryd, or never pushed). The UI confirms before
  overwriting.
- `not_synced` — No Stryd workout on this date.

`sync_target` is `"stryd"` when the user has a Stryd connection, else
`null` — clients can hide the entire sync column when it's `null`.

### POST /api/plan/push-stryd

Push only Praxys-authored plan rows (`source = "ai"`) to the Stryd calendar. Imported Stryd rows are never eligible, even when they are the analytically preferred plan source.

**Request body:**
```json
{ "workout_dates": ["2026-04-11", "2026-04-12"] }
```

**Response:**
```json
{
  "results": [
    { "date": "2026-04-11", "status": "pushed", "workout_id": "stryd_123" }
  ]
}
```

### DELETE /api/plan/stryd-workout/{workout_id}

Remove a workout from Stryd calendar.

### POST /api/plan/upload

Upload an AI-generated training plan as CSV text. The body is `{"csv": "..."}`
where the CSV uses the columns `date,workout_type,planned_duration_min,
planned_distance_km,target_power_min,target_power_max,workout_description`.

**Query params:**
- `mode=replace` *(default)* — delete every future AI plan row for the user,
  then insert the payload. Past rows survive. Used by full-plan generation
  (the AI training-plan skill writes a 28-day window).
- `mode=merge` — upsert by `(user, date, source='ai')`. Only the dates in the
  payload are touched; other AI rows (past and future) are preserved. Used
  for partial edits like shifting a single workout.

**Response:** `{ "status": "saved", "rows": <int>, "mode": "replace"|"merge" }`

### PUT /api/plan/{date}

Upsert a single AI plan workout for the given date (`YYYY-MM-DD`). Replaces any
existing `(user, date, source='ai')` row(s) with one new row from the body;
other dates are untouched. Prefer this over `/plan/upload` when editing one
day so you don't have to round-trip the whole future window.

**Request body:**
```json
{
  "workout_type": "easy",
  "planned_duration_min": 45,
  "planned_distance_km": 8.0,
  "target_power_min": 150,
  "target_power_max": 200,
  "workout_description": "Easy aerobic run"
}
```

**Response:** the upserted row (`id`, `date`, `workout_type`, …, `source`).

### DELETE /api/plan/{date}

Delete the AI plan workout(s) for the given date (`YYYY-MM-DD`). Idempotent —
deleting a missing date returns `{ "status": "deleted", "rows": 0 }`.

## Settings

### GET /api/settings

Current configuration, platform capabilities, and detected thresholds.

**Response:**
```json
{
  "config": {
    "connections": ["garmin", "stryd", "oura"],
    "preferences": { "activities": "garmin", "recovery": "oura", "plan": "ai" },
    "training_base": "power",
    "thresholds": { "cp_watts": null, "lthr_bpm": null, "source": "auto" },
    "zones": { "power": [0.55, 0.75, 0.90, 1.05] },
    "goal": { "distance": "marathon", "target_time_sec": 10800 },
    "science": { "load": "banister_pmc", "zones": "coggan_5zone" }
  },
  "platform_capabilities": {
    "garmin": { "activities": true, "recovery": true, "fitness": true, "plan": false }
  },
  "detected_thresholds": {
    "cp_watts": { "value": 247.8, "source": "stryd" }
  },
  "effective_thresholds": {
    "cp_watts": { "value": 247.8, "origin": "auto (stryd)" }
  },
  "display": { "..." : "..." }
}
```

### PUT /api/settings

Update settings (partial update).

**Request body:** Any subset of config fields:
```json
{
  "training_base": "hr",
  "goal": { "distance": "half_marathon", "target_time_sec": 5400 }
}
```

### GET /api/settings/connections

Return connected platforms and their status. Credentials are never exposed.

**Response:**
```json
{
  "connections": {
    "garmin": {
      "status": "connected",
      "last_sync": "2026-04-10T08:30:00",
      "has_credentials": true
    },
    "stryd": {
      "status": "disconnected",
      "last_sync": null,
      "has_credentials": false
    }
  }
}
```

### POST /api/settings/connections/{platform}

Connect a platform by storing encrypted credentials. Platform must be one of: `garmin`, `stryd`, `oura`.

**Request body (Garmin/Stryd):**
```json
{
  "email": "user@example.com",
  "password": "platform-password",
  "is_cn": false
}
```

**Request body (Oura):**
```json
{
  "token": "oura-personal-access-token"
}
```

**Response:**
```json
{ "status": "connected", "platform": "garmin" }
```

### POST /api/settings/connections/garmin/login

Connect Garmin interactively. Unlike the generic endpoint above (which stores
credentials and defers login to the background sync), this validates the
credentials up front so an account with multi-factor authentication (MFA)
enabled can be prompted for its code. On success the credentials are persisted
and the OAuth tokens cached for future syncs.

**Request body:**
```json
{
  "email": "user@example.com",
  "password": "garmin-password",
  "is_cn": false
}
```

**Response (no MFA):**
```json
{ "status": "connected", "platform": "garmin" }
```

**Response (MFA required):** the client must follow up with the verification
code Garmin sends:
```json
{ "status": "mfa_required", "platform": "garmin" }
```

**Response (bad credentials / rate limited):**
```json
{ "status": "error", "message": "..." }
```

### POST /api/settings/connections/garmin/mfa

Complete a pending interactive Garmin login (see above) with the MFA
verification code. The pending login is process-local and expires after a few
minutes; a wrong code can be retried within that window.

**Request body:**
```json
{ "code": "123456" }
```

**Response:**
```json
{ "status": "connected", "platform": "garmin" }
```

A missing/expired pending login returns
`{ "status": "error", "message": "mfa_session_expired" }`.

### DELETE /api/settings/connections/{platform}

Disconnect a platform and delete stored credentials.

**Response:**
```json
{ "status": "disconnected", "platform": "garmin" }
```

## Science

### GET /api/science

Active theories, available options, and recommendations.

**Response:**
```json
{
  "active": {
    "load": { "id": "banister_pmc", "name": "Banister PMC", "..." : "..." },
    "zones": { "id": "coggan_5zone", "name": "Coggan 5-Zone", "..." : "..." }
  },
  "available": {
    "load": [{ "id": "banister_pmc", "..." : "..." }, { "id": "banister_ultra", "..." : "..." }],
    "zones": [{ "id": "coggan_5zone", "..." : "..." }, { "id": "polarized_3zone", "..." : "..." }]
  },
  "label_sets": [{ "id": "standard", "name": "Standard" }],
  "recommendations": [
    { "pillar": "zones", "recommended_id": "coggan_5zone", "reason": "...", "confidence": 0.85 }
  ]
}
```

### PUT /api/science

Update theory selections.

**Request body:**
```json
{
  "science": { "zones": "polarized_3zone" },
  "zone_labels": "standard"
}
```

## Sync

### GET /api/sync/status

Current sync status for all sources.

**Response:**
```json
{
  "garmin": { "status": "idle|syncing|done|error", "last_sync": "ISO timestamp", "error": null },
  "stryd": { "..." : "..." },
  "oura": { "..." : "..." }
}
```

### POST /api/sync/{source}

Trigger sync for a single source (garmin, stryd, oura). Runs in background.

**Request body (optional):**
```json
{ "from_date": "2025-01-01" }
```

### POST /api/sync

Trigger sync for all configured sources.

## Insights and product events

### GET /api/insights and GET /api/insights/{insight_type}

Returns durable model-generated insights for `training_review` and
`race_forecast`. The list endpoint always omits legacy `daily_brief` rows, and
`GET /api/insights/daily_brief` always returns `{"insight": null}`. Today clients
must render `/api/today.signal` instead.

### POST /api/insights

Pushes a durable insight from a CLI or MCP workflow. `training_review` and
`race_forecast` are accepted. A `daily_brief` push returns HTTP 410 with
`DAILY_BRIEF_DETERMINISTIC` so client prose can never replace the canonical
same-day signal.

### POST /api/insights/{insight_type}/feedback

Submit one vote for the exact generated Coach insight the authenticated user saw.
Uses the current user's id (not demo-source data) and supports `training_review`
or `race_forecast`. Feedback for `daily_brief` returns HTTP 410 with
`DAILY_BRIEF_DETERMINISTIC`.

**Request body:**
```json
{
  "vote": "up",
  "dataset_hash": "64-character SHA-256 hex digest",
  "comment": "Optional, at most 200 characters"
}
```

The current row's `meta.dataset_hash` must match. One submission is accepted per
`(user, insight_type, dataset_hash)`; repeats return `duplicate: true`, even if
that dataset disappears during regeneration and later becomes current again.
The durable `ai_insight_feedback` row and current `AiInsight.meta.feedback`
contain only `dataset_hash`, `vote`, and `submitted_at`. The raw comment is not
persisted; telemetry receives a scrubbed 120-character excerpt.
`GET /api/insights/{insight_type}` also returns server-derived
`feedback_allowed`; it is `false` for read-only demo views, where clients must
hide feedback controls.
**Response:**
```json
{
  "accepted": true,
  "duplicate": false,
  "feedback": {
    "dataset_hash": "...",
    "vote": "up",
    "submitted_at": "2026-07-12T08:30:00+00:00"
  }
}
```

Errors: `404 INSIGHT_NOT_FOUND`, `409 INSIGHT_FEEDBACK_UNVERSIONED`,
`409 INSIGHT_FEEDBACK_STALE`, `410 DAILY_BRIEF_DETERMINISTIC`,
`429 INSIGHT_FEEDBACK_RATE_LIMITED`.

### POST /api/product-events/today-feedback-claim

Reserve the account's Today Decision Check while the client renders it. The
request has no body and returns `{ "accepted": true, "duplicate": false }` when
the prompt may render. A duplicate response means another client has a recent
claim or the prompt was shown within the rolling seven-day cadence. Unconfirmed
claims stop blocking competing renders after two minutes and do not count as
prompt exposure unless a later submission backfills the lost confirmation.

After rendering, the client confirms exposure with `today_feedback_shown` on
`POST /api/product-events`.

### POST /api/product-events

Record an authenticated, privacy-safe product event from web or miniapp. The
server derives `user_id_hash` and timestamp. Extra fields are rejected.
`app_version` must be `develop`, a release CalVer (`YYYY.MM.MICRO`), or an
auto-deploy build (`YYYY.MM.DD.RUN-abcdef0`). Other free-form strings are
rejected so secrets cannot be smuggled into telemetry dimensions.

**Request body:**
```json
{
  "event_name": "today_feedback_submitted",
  "surface": "miniapp",
  "app_version": "2026.07.1",
  "response": "confirmed_plan"
}
```

Allowed events: `app_opened`, `today_brief_rendered`,
`today_reasoning_opened`, `today_feedback_shown`, and
`today_feedback_submitted`. `response` is required only for the submission event
and must be one of `changed_plan`, `confirmed_plan`, `not_helpful`, or
`not_training`.

**Response:** `{ "accepted": true, "duplicate": false }`. Identical lifecycle
events are short-window deduplicated. `today_feedback_shown` confirms a recent
render claim and persists the account-wide seven-day cadence. The first
`today_feedback_submitted` is accepted for a claimed or confirmed prompt
within that seven-day cadence. The two-minute lease limits competing renders;
it does not invalidate a prompt already visible to the user. A submission can
backfill a lost render confirmation, while later answers return
`duplicate: true`.

Errors: `409 PRODUCT_EVENT_PROMPT_NOT_CLAIMED`,
`409 PRODUCT_EVENT_PROMPT_NOT_RENDERED`, and
`429 PRODUCT_EVENT_RATE_LIMITED` after 60 requests per user per minute.

## Health

### GET /api/health

Unauthenticated health check.

**Response:**
```json
{ "status": "ok" }
```

## Common Response Fields

Every endpoint that returns training data includes:

- **`training_base`**: `"power"`, `"hr"`, or `"pace"` — the user's configured training base
- **`display`**: Dynamic labels and units for the active training base:
  - `threshold_label`: "Critical Power" / "Lactate Threshold HR" / "Threshold Pace"
  - `threshold_abbrev`: "CP" / "LTHR" / "T-Pace"
  - `threshold_unit`: "W" / "bpm" / "/km"
  - `load_label`: "RSS" / "TRIMP" / "rTSS"
  - `load_unit`: "" (empty string)
  - `intensity_metric`: "Power" / "Heart Rate" / "Pace"
  - `zone_names`: Zone name array from active theory
  - `trend_label`: "CP Trend" / "LTHR Trend" / "Pace Trend"
