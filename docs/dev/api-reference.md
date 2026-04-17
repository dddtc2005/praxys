# API Reference

All endpoints are under the `/api/` prefix. The API server runs on `http://localhost:8000` by default.

**Authentication:** All data endpoints require `Authorization: Bearer <token>` in the request header. Tokens are obtained via `POST /api/auth/login`.

## Auth

### POST /api/auth/register

Register a new user. First user on a fresh database becomes admin without an invitation code. Subsequent users must provide a valid invitation code.

**Request body:**
```json
{
  "email": "user@example.com",
  "password": "securepassword",
  "invitation_code": "TS-ABCD-1234"
}
```

- `invitation_code` is optional for the first user (auto-admin) or if the email matches `TRAINSIGHT_ADMIN_EMAIL`

**Response:**
```json
{
  "id": "uuid-string",
  "email": "user@example.com",
  "is_superuser": false
}
```

**Error codes:**
- `400 REGISTER_USER_ALREADY_EXISTS` — email already registered
- `400 REGISTER_INVITATION_REQUIRED` — not first user and no code provided
- `400 REGISTER_INVALID_INVITATION` — code is invalid, used, or revoked

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

## Admin

All admin endpoints require `is_superuser=True` on the authenticated user. Returns `403` otherwise.

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

## Today

### GET /api/today

Daily training brief.

Recovery is HRV-based only. When HRV data is missing/insufficient, the API
returns `recovery_analysis.status = "insufficient_data"` and does not provide
recovery suggestions.

**Response:**
```json
{
  "signal": {
    "recommendation": "follow_plan|modify|reduce_intensity|easy|rest",
    "reason": "string",
    "alternatives": [],
    "recovery": { "tsb": 0.6, "hrv_ms": 59.0, "sleep_score": 82.0 },
    "plan": { "workout_type": "easy", "duration_min": "60", "..." : "..." }
  },
  "recovery_analysis": {
    "status": "fresh|normal|fatigued|insufficient_data",
    "hrv": { "today_ms": 59.0, "baseline_mean_ln": 3.87, "trend": "improving" },
    "sleep_score": 82.0,
    "resting_hr": 49.5,
    "rhr_trend": "low|normal|elevated"
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
    { "date": "2026-04-11", "workout_type": "threshold", "duration_min": 65 }
  ],
  "week_load": { "week_label": "W15", "actual": 245.3, "planned": 280.0 },
  "warnings": ["HRV rolling mean declining"],
  "training_base": "power",
  "display": { "threshold_abbrev": "CP", "threshold_unit": "W", "load_label": "RSS" }
}
```

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
      "max": 292, "avg_work": 237, "supra_cp_sessions": 6, "total_quality_sessions": 12
    },
    "distribution": [
      { "name": "Easy", "actual_pct": 72, "target_pct": 80 },
      { "name": "Threshold", "actual_pct": 15, "target_pct": 8 }
    ],
    "zone_ranges": [{ "name": "Easy", "lower": 0, "upper": 136, "unit": "W" }],
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
  "weekly_review": { "weeks": ["W10", "..."], "actual_rss": ["..."], "planned_rss": ["..."] },
  "workout_flags": [{ "date": "...", "flag": "good|bad", "reason": "..." }],
  "sleep_perf": { "..." : "..." },
  "training_base": "power",
  "display": { "..." : "..." }
}
```

## Goal

### GET /api/goal

Race prediction and goal tracking.

**Response:**
```json
{
  "race_countdown": {
    "distance": "marathon",
    "distance_label": "Marathon",
    "mode": "race_goal|cp_milestone",
    "current_cp": 247.8,
    "predicted_time_sec": 13852,
    "target_time_sec": 10800,
    "cp_gap_watts": 70.0,
    "status": "on_track|behind|unlikely",
    "milestones": [{ "cp": 270, "marathon": "~3:50", "reached": false }]
  },
  "cp_trend": { "dates": ["..."], "values": ["..."] },
  "cp_trend_data": { "direction": "improving|stable|falling", "slope_per_month": -3.9 },
  "latest_cp": 247.8,
  "training_base": "power",
  "display": { "..." : "..." }
}
```

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

Upcoming planned workouts (next 14 days).

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
      "description": "WU 10min, 2x20min @235-255W..."
    }
  ],
  "cp_current": 247.8
}
```

### POST /api/plan/push-stryd

Push AI plan workouts to Stryd calendar.

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

### GET /api/plan/stryd-status

Push status for all workouts.

### DELETE /api/plan/stryd-workout/{workout_id}

Remove a workout from Stryd calendar.

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
