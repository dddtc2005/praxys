# Test: Daily Brief

**Prompt:** "Give me my daily brief"

**Expected skill:** `daily-brief`

**Expected tools:**
- `get_daily_brief`

**Assertions:**
- [ ] Response includes training signal (Go/Modify/Rest/Follow Plan)
- [ ] Response mentions recovery status or says no HRV data
- [ ] Response mentions upcoming workout or says none planned
- [ ] Response shows last activity date and summary
- [ ] If data is stale (>24h), suggests syncing
