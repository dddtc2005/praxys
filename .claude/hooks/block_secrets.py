#!/usr/bin/env python
"""PreToolUse hook: refuse Edit/Write against secret or encrypted surfaces.

Blocks edits to:
  - .env / .env.local / .env.production (plaintext secrets)
  - trainsight.db and SQLite companion files (Fernet-encrypted credentials,
    multi-user state)
  - data/garmin/** data/stryd/** data/oura/** (raw synced data)

Rationale: these are managed by sync scripts, the UI, or explicit developer
action. Claude editing them directly tends to corrupt state.

Exit 0 = allow the tool call. Exit 2 = block it and show stderr to Claude.
"""
from __future__ import annotations

import json
import os.path
import sys


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # fail-open: never block on a malformed payload

    raw = payload.get("tool_input", {}).get("file_path", "")
    if not raw:
        return 0

    norm = raw.replace("\\", "/").lower()
    base = os.path.basename(norm)

    blocked_basenames = {".env", ".env.local", ".env.production"}
    if base in blocked_basenames or base.startswith("trainsight.db"):
        _deny(f"secret/db file '{base}'")
        return 2

    for seg in ("/data/garmin/", "/data/stryd/", "/data/oura/"):
        if seg in norm:
            _deny(f"synced data under '{seg.strip('/')}'")
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
