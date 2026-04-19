---
event: SessionStart
---

Check the Praxys connection mode:

If `PRAXYS_URL` (or legacy `TRAINSIGHT_URL`) is set (recommended production mode):
- Call the `get_sync_status` tool to check data freshness
- If any platform's last sync is older than 24 hours, suggest: "Your data is stale. Want me to trigger a sync?"
- If data is fresh, stay silent

If neither URL is set (local development mode):
- This is dev/debug mode. Stay silent unless the user asks about sync or data.
