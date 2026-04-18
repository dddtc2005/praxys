#!/usr/bin/env python
"""PreToolUse hook: refuse Edit/Write against secret or encrypted surfaces.

Blocks edits to:
  - .env and any .env.<anything> (plaintext secrets)
  - trainsight.db and SQLite companion files (Fernet-encrypted credentials,
    multi-user state)
  - data/garmin/** data/stryd/** data/oura/** (raw synced data)

Rationale: these are managed by sync scripts, the UI, or explicit developer
action. Claude editing them directly tends to corrupt state.

Exit 0 = allow the tool call. Exit 2 = block it and show stderr to Claude.

Security posture: this hook is a guardrail. On malformed input, unknown
tool names, or missing fields it fails CLOSED (exit 2) — a mute guardrail
is worse than a noisy one.
"""
from __future__ import annotations

import json
import os.path
import sys


KNOWN_WRITE_TOOLS = {"Edit", "Write"}


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        _deny(
            f"could not parse hook payload ({exc.msg}). "
            "Denying to fail safe — the guardrail cannot make a decision."
        )
        return 2

    tool_name = payload.get("tool_name", "")
    if tool_name not in KNOWN_WRITE_TOOLS:
        _deny(
            f"matcher fired for tool '{tool_name}' but this hook only "
            "understands Edit/Write. Denying to fail safe. Narrow the "
            "matcher in .claude/settings.json or extend this hook."
        )
        return 2

    raw = payload.get("tool_input", {}).get("file_path", "")
    if not raw:
        _deny(
            "tool_input.file_path was missing or empty. "
            "Denying to fail safe — the guardrail cannot verify the target."
        )
        return 2

    norm = raw.replace("\\", "/").lower()
    base = os.path.basename(norm)

    if base == ".env" or base.startswith(".env."):
        _deny(f"env file '{base}'")
        return 2

    if (
        base == "trainsight.db"
        or base.startswith("trainsight.db-")
        or base.startswith("trainsight.db.")
    ):
        _deny(f"sqlite file '{base}'")
        return 2

    parts = norm.split("/")
    for i in range(len(parts) - 1):
        if parts[i] == "data" and parts[i + 1] in ("garmin", "stryd", "oura"):
            _deny(f"synced data under 'data/{parts[i + 1]}'")
            return 2

    return 0


def _deny(reason: str) -> None:
    print(
        f"Blocked: refusing to Edit/Write {reason}. "
        f"These paths are managed by sync scripts or the UI. "
        f"If you really need to change this file, do it outside Claude Code "
        f"or temporarily disable .claude/hooks/block_secrets.py.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    sys.exit(main())
