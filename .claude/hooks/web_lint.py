#!/usr/bin/env python
"""PostToolUse hook: run ESLint on the single web/ file just edited.

Runs fast (per-file, not the whole project), gives Claude immediate
feedback on rule violations and import errors. Silent when the edit is
not a .ts/.tsx file inside web/.

Does not run tsc -b: that's a project-wide check best left to CI and
`npm run build`. Per-file eslint catches the majority of issues.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


TAIL_LINES = 25


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    raw = payload.get("tool_input", {}).get("file_path", "")
    if not raw:
        return 0

    path = raw.replace("\\", "/")
    if not (path.endswith((".ts", ".tsx")) and "/web/" in path):
        return 0

    idx = path.index("/web/")
    web_root = Path(path[: idx + len("/web")])
    rel = path[idx + len("/web/"):]

    if not (web_root / "package.json").exists():
        return 0

    cmd = f'npx --no-install eslint "{rel}"'
    try:
        result = subprocess.run(
            cmd,
            cwd=str(web_root),
            capture_output=True,
            text=True,
            timeout=45,
            shell=True,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return 0  # never block the edit on tooling failure

    output = (result.stdout + result.stderr).strip()
    if not output or result.returncode == 0:
        return 0

    lines = output.splitlines()[-TAIL_LINES:]
    print(f"ESLint ({rel}):")
    print("\n".join(lines))
    return 0  # never block — report-only


if __name__ == "__main__":
    sys.exit(main())
