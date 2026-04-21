"""JWT secret resolution — shared by api/auth.py and api/users.py.

The JWT signing key gates every request. If both consumers are allowed to
silently fall back to a shared hardcoded string, any attacker who reads this
repository can forge a token for any user. This module:

* Reads ``PRAXYS_JWT_SECRET`` (or legacy ``TRAINSIGHT_JWT_SECRET``).
* In production (detected via Azure App Service's ``WEBSITE_SITE_NAME``
  environment variable — the same marker ``api/main.py`` uses to gate CORS
  middleware) refuses to boot without an explicit secret.
* In local development, generates a random process-scoped secret on first
  access and memoizes it so ``api.auth`` and ``api.users`` agree within a
  single run. Tokens don't survive server restarts in this mode, which is
  intentional — dev reloads force re-login.
"""
import logging
import os
import secrets

from api.env_compat import getenv_compat

logger = logging.getLogger(__name__)

_cached_secret: str | None = None


def _is_production() -> bool:
    """True on Azure App Service (and anywhere else that sets this var)."""
    return bool(os.environ.get("WEBSITE_SITE_NAME"))


def get_jwt_secret() -> str:
    """Return the JWT signing secret.

    Raises RuntimeError in production if no secret is configured; in dev,
    generates a random per-process secret the first time it's called.
    """
    global _cached_secret
    if _cached_secret is not None:
        return _cached_secret

    configured = getenv_compat("JWT_SECRET")
    if configured:
        _cached_secret = configured
        return _cached_secret

    if _is_production():
        raise RuntimeError(
            "PRAXYS_JWT_SECRET is not set. Production deployments must provide "
            "an explicit JWT signing secret — generate one with "
            "`python -c 'import secrets; print(secrets.token_urlsafe(48))'` "
            "and set it as a WebApp configuration value."
        )

    _cached_secret = secrets.token_urlsafe(48)
    logger.warning(
        "PRAXYS_JWT_SECRET not set — generated a random per-process secret. "
        "Tokens will not survive server restarts. Set PRAXYS_JWT_SECRET in "
        ".env to avoid being logged out on reload."
    )
    return _cached_secret


def reset_cache_for_tests() -> None:
    """Tests that mutate the environment must invalidate the memoized secret."""
    global _cached_secret
    _cached_secret = None
