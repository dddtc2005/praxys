"""Environment variable compatibility shim for the Trainsight → Praxys rename.

Reads the new PRAXYS_<suffix> prefix first; falls back to legacy
TRAINSIGHT_<suffix> with a one-time deprecation warning per key.

Remove after 2026-05-19 (one release deprecation window). By then every
active deployment should have updated its .env files.
"""
import logging
import os
from typing import Optional

_warned_keys: set[str] = set()
_logger = logging.getLogger(__name__)


def getenv_compat(key_suffix: str, default: Optional[str] = None) -> Optional[str]:
    """Read PRAXYS_<suffix> first, then TRAINSIGHT_<suffix>, then default.

    If only the legacy TRAINSIGHT_<suffix> is set, log a deprecation warning
    once per process per key.
    """
    new_key = f"PRAXYS_{key_suffix}"
    legacy_key = f"TRAINSIGHT_{key_suffix}"

    fresh = os.environ.get(new_key)
    if fresh is not None:
        return fresh

    legacy = os.environ.get(legacy_key)
    if legacy is not None:
        if legacy_key not in _warned_keys:
            _logger.warning(
                "%s is deprecated; rename to %s. Legacy name will be removed after 2026-05-19.",
                legacy_key, new_key,
            )
            _warned_keys.add(legacy_key)
        return legacy

    return default
