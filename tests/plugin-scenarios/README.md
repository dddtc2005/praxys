# Plugin Test Scenarios

Integration test scenarios for the Trainsight plugin. Each file is an independent
test case that can be executed in Claude Code or Copilot CLI.

## Prerequisites

- Backend running: `python -m uvicorn api.main:app --reload`
- Plugin installed: `claude plugin add ./plugins/trainsight`
- At least one platform connected and synced

## How to Run

**Single scenario:** Open Claude Code and say "Run the test in tests/plugin-scenarios/01-daily-brief.md"

**All scenarios:** "Run all plugin test scenarios in tests/plugin-scenarios/"

## Automated MCP Tool Tests

For CI without an AI assistant:
```bash
python -m pytest tests/test_mcp_tools.py -v
```
