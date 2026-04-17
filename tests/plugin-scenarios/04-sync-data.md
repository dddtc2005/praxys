# Test: Sync Data

**Prompt:** "Sync my training data"

**Expected skill:** `sync-data`

**Expected tools:**
- `trigger_sync`
- `get_sync_status`

**Assertions:**
- [ ] Response triggers sync for connected platforms only
- [ ] Response shows sync progress or completion
- [ ] If no platforms connected, suggests connecting first
