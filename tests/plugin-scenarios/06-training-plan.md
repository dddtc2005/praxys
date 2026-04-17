# Test: Generate Training Plan

**Prompt:** "Generate a 4-week training plan for me"

**Expected skill:** `training-plan`

**Expected tools:**
- `get_training_context` (for athlete profile)
- `push_training_plan` (after user approves)

**Assertions:**
- [ ] Fetches training context before generating
- [ ] Generated plan has 28 days of workouts
- [ ] Plan includes rest days (at least 1 per week)
- [ ] Power targets are within 40-130% of current CP
- [ ] Presents plan as a formatted table for review
- [ ] Asks for user approval before saving
