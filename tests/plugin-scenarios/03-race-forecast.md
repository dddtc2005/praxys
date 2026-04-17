# Test: Race Forecast

**Prompt:** "What's my marathon prediction?"

**Expected skill:** `race-forecast`

**Expected tools:**
- `get_race_forecast`

**Assertions:**
- [ ] Response includes predicted finish time
- [ ] Response mentions current CP/threshold value
- [ ] If goal is set, shows feasibility assessment
- [ ] If no goal, suggests setting one
