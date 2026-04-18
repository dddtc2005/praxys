---
name: setup
description: >-
  Configure Trainsight: connect data sources (Garmin, Stryd, Oura), set training
  base (power/HR/pace), configure thresholds (CP, LTHR, pace), set race goals,
  and manage source preferences. Use this skill whenever the user asks to "connect
  garmin", "set up stryd", "add oura", "change training base", "set my CP",
  "set my goal", "configure preferences", "initial setup", "set threshold",
  "switch to HR-based training", "disconnect a platform", or any request to
  configure the training system. Also use when the user reports sync failures
  or missing connections.
---

# Trainsight Setup

Guide the user through configuring their training system.

## Before You Start

Call `get_settings` to understand current state, then call `get_connections`
to see which platforms are connected.

## Credential Safety

**Never ask the user to type passwords, tokens, or secrets in the conversation.**
Credentials typed in chat are logged in transcripts and visible in scrollback.
Instead, direct the user to connect platforms via the **web Settings page**
where credentials are entered in form fields and stored encrypted.

If the user is CLI-only and insists on connecting without the web UI, use the
`connect_platform` MCP tool — but warn them that the credentials will pass
through the conversation. Prefer the web Settings page.

## Configuration Areas

### 1. Platform Connections

Platforms are connected via the web Settings page or the `connect_platform` tool.
Credentials are encrypted with a per-user key and stored securely in the database.

| Platform | Required Credentials | How to Get |
|----------|---------------------|------------|
| Garmin | Email + password | Garmin Connect account |
| Garmin China | Email + password + is_cn flag | Garmin Connect CN account |
| Stryd | Email + password | Stryd account (stryd.com) |
| Oura | Personal access token | Generate at cloud.ouraring.com/personal-access-tokens |

To check connections: call `get_connections`
To disconnect: call `disconnect_platform` with the platform name

Platform capabilities:
- **activities**: garmin, stryd, coros
- **recovery**: garmin, oura
- **fitness**: garmin, stryd, coros (auto-merged)
- **plan**: garmin, stryd, coros, ai

### 2. Training Base

The training base determines which metric drives all analysis:

| Base | Threshold | Load Metric | Best When |
|------|-----------|-------------|-----------|
| `power` | CP (watts) | RSS | Has Stryd or power meter |
| `hr` | LTHR (bpm) | TRIMP | Has HR monitor, no power |
| `pace` | Threshold pace (sec/km) | rTSS | GPS-only, no HR or power |

Call `update_settings` with `{"training_base": "power"}` (or "hr"/"pace").

### 3. Thresholds

Thresholds can be auto-detected from connected platforms or set manually:

- `"source": "auto"` — system detects from connected platforms
- `"source": "manual"` — only use manually entered values

When the user provides a threshold, call `update_settings` with the thresholds
dict. Manual values override auto-detected ones even in auto mode.

### 4. Goal Configuration

- **Race mode**: set `race_date` + `distance` + optional `target_time_sec`
- **Continuous improvement**: leave `race_date` empty, set `distance` for predictions

Help convert times: "sub-3 marathon" = 10800 sec, "sub-45 10K" = 2700 sec.
Call `update_settings` with `{"goal": {...}}`.

### 5. Zone Boundaries (Advanced)

4 boundaries define 5 zones. Only modify if the user has specific preferences.
For zone theory selection (Coggan vs Seiler), use the `science` skill.

### 6. Auto Sync Frequency

Use `get_sync_settings` to read the current auto-sync interval and
`set_sync_frequency` to change it (allowed values: 6, 12, 24 hours).
Default is every 6 hours.

## First-Time Setup Checklist

1. Call `get_connections` — check what's connected
2. Guide user to connect platforms via web Settings page
3. After connecting, call `trigger_sync` to pull initial data
4. Set `training_base` based on available data (power if they have Stryd)
5. Set `goal` if they have a race target
6. Verify data loaded: call `get_daily_brief` to confirm
