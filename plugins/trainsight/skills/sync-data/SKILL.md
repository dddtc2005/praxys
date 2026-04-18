---
name: sync-data
description: >-
  Sync training data from Garmin, Stryd, and/or Oura Ring. Use this skill when
  the user asks to "sync my data", "pull training data", "update activities",
  "refresh garmin data", "sync oura", "sync stryd", "download new runs",
  "get latest workouts", "backfill data", or any request to fetch training data
  from connected platforms. Also use when the user wants to check sync status.
---

# Sync Training Data

Pull the latest training data from connected platforms (Garmin, Stryd, Oura)
into the database.

## Running a Sync

Call the `trigger_sync` MCP tool. Optionally pass a `sources` list to limit
which platforms to sync (e.g., `["garmin", "stryd"]`).

To check the current sync state, call the `get_sync_status` MCP tool.

## How Sync Works

1. The backend reads the user's encrypted credentials from the database
2. Fetches new data from platform APIs (Garmin Connect, Stryd, Oura Ring)
3. Parses the API responses and writes directly to the SQLite database
4. Updates the `last_sync` timestamp on the connection record

Sync is idempotent — running it multiple times is safe (existing records are skipped).

A background scheduler also runs auto syncs for all connected platforms.
Users can inspect and change the interval (guardrailed to 6/12/24 hours) via:
- `get_sync_settings`
- `set_sync_frequency`

Default is every 6 hours.

Webhook/subscription notes:
- Stryd and Oura rely on polling (no webhook subscription in current integration)
- Garmin push delivery requires a separate partner integration, so Trainsight
  currently uses scheduled sync for Garmin too

## Reading Sync Status

The `get_sync_status` tool returns per-platform status:

| Field | Meaning |
|-------|---------|
| `status` | `idle`, `syncing`, `done`, or `error` |
| `last_sync` | ISO timestamp of last successful sync |
| `connected` | Whether credentials are stored for this platform |
| `error` | Error message if status is `error` |

## Presenting Results

Format the output as a summary table for the user:

| Source | Status | Last Sync |
|--------|--------|-----------|
| Garmin | connected | 2h ago |
| Stryd | connected | 2h ago |
| Oura | error | Token expired |

If a source is not connected, suggest the user connect it via the Settings page
or the `setup` skill.

If a source has `error` status, suggest common fixes:
- Garmin: token expiry — reconnect in Settings
- Stryd: 401 — check password in Settings
- Oura: 401 — regenerate token at cloud.ouraring.com, update in Settings
