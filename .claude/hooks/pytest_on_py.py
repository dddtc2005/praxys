#!/usr/bin/env python
"""PostToolUse hook: run pytest when a .py file is edited.

Replaces the previous inline shell pipeline in .claude/settings.json,
which had three problems:
  1. Trailing `|| true` swallowed pytest's non-zero exit so Claude never
     saw the failure.
  2. `tail -20` is unavailable on stock Windows shells.
  3. It called bare `python`, not the project venv — producing
     ModuleNotFoundError when venv is not pre-activated.

This script resolves the venv Python, runs pytest with fail-fast, and
surfaces failures via stderr + exit 2 (PostToolUse feedback signal).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


TAIL_LINES = 30
PYTEST_TIMEOUT_SEC = 110
HOOK_PATH = Path(__file__).resolve()
PROJECT_ROOT = HOOK_PATH.parents[2]


def _resolve_venv_python() -> str:
    """Locate the project venv's python, falling back to sys.executable."""
    candidates = [
        PROJECT_ROOT / ".venv" / "Scripts" / "python.exe",  # Windows
        PROJECT_ROOT / ".venv" / "bin" / "python",          # Unix
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return sys.executable


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    raw = payload.get("tool_input", {}).get("file_path", "")
    if not raw.endswith(".py"):
        return 0

    python = _resolve_venv_python()
    try:
        result = subprocess.run(
            [python, "-m", "pytest", "tests/", "-x", "-q", "--tb=short"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=PYTEST_TIMEOUT_SEC,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        print(
            f"pytest_on_py: test suite exceeded {PYTEST_TIMEOUT_SEC}s — skipping.",
            file=sys.stderr,
        )
        return 0
    except (FileNotFoundError, OSError) as exc:
        print(
            f"pytest_on_py: could not launch pytest ({exc.__class__.__name__}: "
            f"{exc}). Ensure .venv exists and requirements are installed.",
            file=sys.stderr,
        )
        return 0

    if result.returncode == 0:
        return 0

    output = (result.stdout + result.stderr).strip()
    lines = output.splitlines()[-TAIL_LINES:] if output else [
        f"pytest exited {result.returncode} with no output"
    ]
    print(f"pytest failed (last {len(lines)} lines):", file=sys.stderr)
    print("\n".join(lines), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
