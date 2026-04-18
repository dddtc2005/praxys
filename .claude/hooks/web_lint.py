#!/usr/bin/env python
"""PostToolUse hook: run ESLint on the single web/ file just edited.

Runs fast (per-file, not the whole project), gives Claude immediate
feedback on rule violations and import errors. Silent when the edit is
not a .ts/.tsx file inside the project's web/ directory.

Does not run tsc -b: that's a project-wide check best left to CI and
`npm run build`. Per-file eslint catches the majority of issues.

Behavior:
  - Lint errors: print to stderr, exit 2 so Claude sees the feedback.
  - Tooling missing (no node_modules, no npx): print a one-line notice
    to stderr, exit 0. A silent skip would hide the hook's no-op.
  - Anything else (not a TS file, not under web/): exit 0 silently.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


TAIL_LINES = 25
HOOK_PATH = Path(__file__).resolve()
PROJECT_ROOT = HOOK_PATH.parents[2]
WEB_ROOT = PROJECT_ROOT / "web"


def _resolve_in_project(raw: str) -> Path | None:
    """Resolve a Claude-supplied file_path against the project root.

    Returns None if it can't be resolved. Accepts absolute paths,
    repo-relative paths (``web/src/Foo.tsx``), and ``./``-prefixed paths.
    """
    try:
        p = Path(raw)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p.resolve(strict=False)
    except (OSError, ValueError):
        return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0  # post-hook: silently skip on bad payload (tool already ran)

    raw = payload.get("tool_input", {}).get("file_path", "")
    if not raw:
        return 0

    abs_path = _resolve_in_project(raw)
    if abs_path is None:
        return 0

    web_root_resolved = WEB_ROOT.resolve(strict=False)
    try:
        rel_path = abs_path.relative_to(web_root_resolved)
    except ValueError:
        return 0  # not under project's web/

    rel = rel_path.as_posix()
    if not rel.endswith((".ts", ".tsx")):
        return 0

    if not (WEB_ROOT / "package.json").exists():
        return 0
    if not (WEB_ROOT / "node_modules").exists():
        print(
            "web_lint: web/node_modules missing — skipping ESLint. "
            "Run `cd web && npm install` to enable this hook.",
            file=sys.stderr,
        )
        return 0

    npx = "npx.cmd" if sys.platform == "win32" else "npx"
    try:
        result = subprocess.run(
            [npx, "--no-install", "eslint", rel],
            cwd=str(WEB_ROOT),
            capture_output=True,
            text=True,
            timeout=45,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        print("web_lint: ESLint timed out after 45s — skipping.", file=sys.stderr)
        return 0
    except (FileNotFoundError, OSError) as exc:
        print(
            f"web_lint: could not run ESLint ({exc.__class__.__name__}: {exc}). "
            "Install node + npm so `npx` is on PATH.",
            file=sys.stderr,
        )
        return 0

    output = (result.stdout + result.stderr).strip()

    if result.returncode == 0:
        return 0

    lines = output.splitlines()[-TAIL_LINES:] if output else [
        f"eslint exited {result.returncode} with no output"
    ]
    print(f"ESLint ({rel}):", file=sys.stderr)
    print("\n".join(lines), file=sys.stderr)
    return 2  # PostToolUse exit 2 surfaces stderr to Claude as feedback


if __name__ == "__main__":
    sys.exit(main())
