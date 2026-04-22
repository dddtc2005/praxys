"""JWT secret resolution — shared by api/auth.py and api/users.py.

The JWT signing key gates every request: whoever knows it can forge a token
for any user_id. A hardcoded repo-committed default would defeat the whole
auth story, so this module makes a missing secret a fail-closed condition
in every deployment context that isn't explicitly marked for dev use.

Resolution order on every call:

1. If ``PRAXYS_JWT_SECRET`` (or legacy ``TRAINSIGHT_JWT_SECRET``) is set in
   the environment, return it. Not cached, so operators who patch the env
   var live (Azure Portal save → app restart, or any hot-reload path) see
   the new value on the next request without needing to prove a cache
   invalidated.
2. Otherwise, if the process is running in a dev-acknowledged context —
   ``PRAXYS_ENV=development`` explicitly set, or pytest is the caller
   (``PYTEST_CURRENT_TEST`` is set automatically) — generate a random
   per-process secret on first access and memoize it so auth.py and
   users.py agree within the run. Tokens don't survive restarts, which is
   the intended dev tradeoff.
3. Otherwise raise ``RuntimeError``. Azure App Service sets
   ``WEBSITE_SITE_NAME`` automatically, Docker/AWS/bare-metal set nothing
   — in both cases we refuse to serve. Operators must either configure a
   real secret or explicitly opt into ephemeral dev mode.
"""
import logging
import os
import secrets

from api.env_compat import getenv_compat

logger = logging.getLogger(__name__)

_cached_generated_secret: str | None = None


def _is_dev_context() -> bool:
    """True when the caller has explicitly opted into ephemeral secrets.

    Two signals are honored: ``PRAXYS_ENV=development`` (developer sets this
    in their .env once) and ``PYTEST_CURRENT_TEST`` (pytest sets this per
    test, so the test suite works without repo-wide configuration).
    """
    env = (os.environ.get("PRAXYS_ENV") or os.environ.get("TRAINSIGHT_ENV") or "").lower()
    if env == "development":
        return True
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def get_jwt_secret() -> str:
    """Return the JWT signing secret, fail-closed on misconfiguration."""
    global _cached_generated_secret

    configured = getenv_compat("JWT_SECRET")
    if configured:
        return configured

    if not _is_dev_context():
        raise RuntimeError(
            "PRAXYS_JWT_SECRET is not set. All non-dev deployments must provide "
            "an explicit JWT signing secret — generate one with "
            "`python -c 'import secrets; print(secrets.token_urlsafe(48))'` "
            "and set it in the runtime environment (Azure App Service "
            "configuration, Docker env, etc.). For local development, either "
            "set PRAXYS_JWT_SECRET in .env or mark the environment with "
            "PRAXYS_ENV=development."
        )

    if _cached_generated_secret is None:
        _cached_generated_secret = secrets.token_urlsafe(48)
        logger.warning(
            "PRAXYS_JWT_SECRET not set — generated a random per-process secret. "
            "Tokens will not survive server restarts. Set PRAXYS_JWT_SECRET in "
            ".env to avoid being logged out on reload."
        )
    return _cached_generated_secret


def _reset_cache_for_tests() -> None:
    """Invalidate the memoized dev secret. Pytest-only.

    Refuses to run outside a pytest context because a stray call from a
    runtime code path could split-brain the JWT secret across workers
    (one worker rotates, others keep the old value).
    """
    if os.environ.get("PYTEST_CURRENT_TEST") is None:
        raise RuntimeError("_reset_cache_for_tests() may only be called from pytest")
    global _cached_generated_secret
    _cached_generated_secret = None
