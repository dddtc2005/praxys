"""Tests for JWT secret resolution.

A hardcoded default for PRAXYS_JWT_SECRET would let anyone with repo access
forge tokens for any user. The resolver must:
 * fail-fast in production (Azure App Service) when the secret is missing,
 * auto-generate a stable process-scoped secret in dev so tests and reloads
   work without hand-configuring a key,
 * return the configured value when the env var is set.
"""
import pytest

from api import auth_secrets


@pytest.fixture(autouse=True)
def _reset_cache():
    auth_secrets.reset_cache_for_tests()
    yield
    auth_secrets.reset_cache_for_tests()


def test_production_without_secret_raises(monkeypatch):
    """Azure deploys without PRAXYS_JWT_SECRET must refuse to boot."""
    monkeypatch.setenv("WEBSITE_SITE_NAME", "trainsight-app")
    monkeypatch.delenv("PRAXYS_JWT_SECRET", raising=False)
    monkeypatch.delenv("TRAINSIGHT_JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="PRAXYS_JWT_SECRET"):
        auth_secrets.get_jwt_secret()


def test_production_with_secret_returns_it(monkeypatch):
    monkeypatch.setenv("WEBSITE_SITE_NAME", "trainsight-app")
    monkeypatch.setenv("PRAXYS_JWT_SECRET", "production-value")
    assert auth_secrets.get_jwt_secret() == "production-value"


def test_dev_without_secret_generates_stable_process_secret(monkeypatch):
    """Dev should auto-generate a secret, but calls within a process agree."""
    monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)
    monkeypatch.delenv("PRAXYS_JWT_SECRET", raising=False)
    monkeypatch.delenv("TRAINSIGHT_JWT_SECRET", raising=False)

    first = auth_secrets.get_jwt_secret()
    second = auth_secrets.get_jwt_secret()
    assert first == second
    assert first != "dev-secret-change-in-production!!", (
        "Must not fall back to the old known hardcoded string."
    )
    assert len(first) >= 32, "Generated secret should be at least 32 chars"


def test_explicit_secret_wins_over_generation(monkeypatch):
    """If PRAXYS_JWT_SECRET is set, use it verbatim — never fall back to auto."""
    monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)
    monkeypatch.setenv("PRAXYS_JWT_SECRET", "explicit-dev-value")
    assert auth_secrets.get_jwt_secret() == "explicit-dev-value"


def test_legacy_env_var_still_works(monkeypatch):
    """Back-compat: TRAINSIGHT_JWT_SECRET feeds the resolver during the rename window."""
    monkeypatch.delenv("WEBSITE_SITE_NAME", raising=False)
    monkeypatch.delenv("PRAXYS_JWT_SECRET", raising=False)
    monkeypatch.setenv("TRAINSIGHT_JWT_SECRET", "legacy-value")
    assert auth_secrets.get_jwt_secret() == "legacy-value"
