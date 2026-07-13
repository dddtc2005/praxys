"""Backend build version metadata.

Mirrors the mini program's ``wx.getAccountInfoSync`` pattern: the running
build's version is baked at deploy time and returned by ``/api/version``
so the frontend (and any operator hitting the URL) can tell which
build is live.

Resolution order:

1. ``PRAXYS_API_VERSION`` env var — set on the App Service so a redeploy
   that doesn't rebuild the artifact (e.g. an Azure config-only restart)
   still surfaces the right value.
2. ``api/_build_version.txt`` written by the deploy workflow next to
   this module — keeps the artifact self-describing so a future deploy
   target (Tencent CN, etc.) doesn't need Azure-specific app settings.
3. ``"develop"`` — the local-dev fallback that mirrors the mini
   program's ``envVersion === 'develop'`` branch.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_BUILD_FILE = Path(__file__).resolve().parent / "_build_version.txt"
_BUILD_VERSION_PATTERN = (
    r"(?:develop|[0-9]{4}\.(?:0[1-9]|1[0-2])\."
    r"(?:(?:0[1-9]|[12][0-9]|3[01])\."
    r"[0-9]{1,8}-[0-9a-f]{7}|[0-9]{1,4}))"
)
_BUILD_VERSION_RE = re.compile(rf"^{_BUILD_VERSION_PATTERN}$")
_BUILD_VERSION_IN_TEXT_RE = re.compile(
    rf"(?<![A-Za-z0-9_.-]){_BUILD_VERSION_PATTERN}"
    rf"(?![A-Za-z0-9_-]|\.[A-Za-z0-9_-])"
)


def is_valid_build_version(value: object) -> bool:
    """Return whether *value* is a supported release or CI build identifier."""
    return isinstance(value, str) and bool(_BUILD_VERSION_RE.fullmatch(value.strip()))


def find_valid_build_versions(text: str) -> tuple[str, ...]:
    """Return unique supported build identifiers embedded in ``text``."""
    return tuple(
        dict.fromkeys(
            match.group(0) for match in _BUILD_VERSION_IN_TEXT_RE.finditer(text)
        )
    )


def get_api_version() -> str:
    """Return the build version string used by ``/api/version``."""
    env_value = os.environ.get("PRAXYS_API_VERSION")
    if env_value:
        return env_value.strip()
    if _BUILD_FILE.exists():
        text = _BUILD_FILE.read_text(encoding="utf-8").strip()
        if text:
            return text
    return "develop"
