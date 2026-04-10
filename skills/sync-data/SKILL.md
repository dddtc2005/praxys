---
name: sync-data
description: >-
  Sync training data from Garmin, Stryd, and/or Oura Ring to local CSV files.
  Use this skill when the user asks to "sync my data", "pull training data",
  "update activities", "refresh garmin data", "sync oura", "sync stryd",
  "download new runs", "get latest workouts", "backfill data", "sync from
  last month", or any request to fetch training data from connected platforms.
  Also use when the user wants to check what data they have or when their
  last sync was.
---

# Sync Training Data

Pull the latest training data from connected platforms (Garmin, Stryd, Oura)
into local CSV files.

## Running a Sync

Run the sync report script from the project root:

```bash
python skills/sync-data/scripts/sync_report.py --pretty
```

### Options

| Flag | Purpose | Example |
|------|---------|---------|
| `--pretty` | Human-readable JSON output | Always use for display |
| `--from-date YYYY-MM-DD` | Backfill from a specific date | `--from-date 2025-01-01` |
| `--skip source [source...]` | Skip specific sources | `--skip oura` |

Default sync window is the last 7 days. Use `--from-date` for historical backfill.

## Reading the Output

The script outputs JSON with per-source results:

```json
{
  "sources": {
    "oura": {
      "status": "ok",
      "rows_before": 120,
      "rows_after": 127,
      "new_rows": 7,
      "date_range": ["2026-04-04", "2026-04-10"],
      "files": ["data/oura/sleep.csv", "data/oura/readiness.csv"]
    },
    "garmin": { "status": "ok", ... },
    "stryd": { "status": "skipped", "reason": "STRYD_PASSWORD not set" }
  },
  "sync_date": "2026-04-10",
  "from_date": "2026-04-03"
}
```

### Status Values

| Status | Meaning |
|--------|---------|
| `ok` | Sync completed successfully |
| `skipped` | Missing credentials (see `reason` field) |
| `error` | Sync failed (see `reason` field) |
| `user_skipped` | User passed `--skip` for this source |

## Presenting Results

Format the output as a summary table for the user:

| Source | Status | New Rows | Date Range |
|--------|--------|----------|------------|
| Garmin | ok | +8 activities | Apr 4 – Apr 10 |
| Stryd | ok | +8 power records | Apr 4 – Apr 10 |
| Oura | ok | +7 sleep/readiness | Apr 4 – Apr 10 |

If any source has `skipped` status, suggest the user run the `setup` skill to
configure credentials.

If any source has `error` status, show the error message and suggest common fixes:
- Garmin: token expiry → run `python -m sync.bootstrap_garmin_tokens`
- Stryd: 401 → check password
- Oura: 401 → regenerate token at cloud.ouraring.com

## Data Files Produced

| Source | CSV Files |
|--------|-----------|
| Garmin | `data/garmin/activities.csv`, `activity_splits.csv`, `daily_metrics.csv`, `lactate_threshold.csv` |
| Stryd | `data/stryd/power_data.csv`, `activity_splits.csv`, `training_plan.csv` |
| Oura | `data/oura/sleep.csv`, `readiness.csv` |

All CSVs use deduplication — running sync multiple times is safe and idempotent.
