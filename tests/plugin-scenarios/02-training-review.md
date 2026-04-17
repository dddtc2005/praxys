# Test: Training Review

**Prompt:** "Review my training from the past few weeks"

**Expected skill:** `training-review`

**Expected tools:**
- `get_training_review`

**Assertions:**
- [ ] Response includes zone distribution analysis
- [ ] Response mentions fitness/fatigue trend
- [ ] Response includes specific suggestions
- [ ] Numbers use correct units (W for power, bpm for HR)
- [ ] If insufficient data, says so clearly
