# Test: Settings Update

**Prompt:** "Change my training base to heart rate"

**Expected skill:** `setup` or direct tool use

**Expected tools:**
- `update_settings`
- `get_settings` (to confirm)

**Assertions:**
- [ ] Training base changes to "hr"
- [ ] Response confirms the change
- [ ] Mentions that zone calculations will use LTHR

**Cleanup:** After test, revert: "Change my training base back to power"
