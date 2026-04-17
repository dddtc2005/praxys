# Test: Setup / View Configuration

**Prompt:** "Show me my current setup"

**Expected skill:** `setup`

**Expected tools:**
- `get_settings`
- `get_connections`

**Assertions:**
- [ ] Response lists connected platforms and their status
- [ ] Response shows training base selection
- [ ] Response shows goal configuration (or says none set)
- [ ] Does NOT reveal any credentials
