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
from pathlib import Path

_BUILD_FILE = Path(__file__).resolve().parent / "_build_version.txt"


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
