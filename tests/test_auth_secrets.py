"""Tests for JWT secret resolution.

A hardcoded default for the JWT secret would let anyone with repo access
forge tokens for any user. The resolver must:
 * fail fast in any deployment not explicitly marked as dev,
 * auto-generate a stable process-scoped secret only under an explicit dev
   opt-in (PRAXYS_ENV=development or pytest) so local work is frictionless
   without widening the prod threat surface,
 * return an explicit value verbatim when set.
"""
import pytest

from api import auth_secrets


@pytest.fixture(autouse=True)
def _reset_cache():
    auth_secrets._reset_cache_for_tests()
    yield
    auth_secrets._reset_cache_for_tests()


def test_non_dev_without_secret_raises(monkeypatch):
    """Any runtime missing both a secret and a dev marker must refuse to serve."""
    # Strip BOTH pytest and explicit dev markers so this simulates a prod env.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("PRAXYS_ENV", raising=False)
    monkeypatch.delenv("TRAINSIGHT_ENV", raising=False)
    monkeypatch.delenv("PRAXYS_JWT_SECRET", raising=False)
    monkeypatch.delenv("TRAINSIGHT_JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="PRAXYS_JWT_SECRET"):
        auth_secrets.get_jwt_secret()


def test_azure_without_secret_raises_even_with_pytest_marker(monkeypatch):
    """Azure is production even if the test harness happens to leak its marker.

    Belt-and-suspenders: WEBSITE_SITE_NAME alone is not the guard, but we
    should not accidentally auto-generate just because pytest is in scope.
    This locks in that PRAXYS_ENV=development (not pytest) is the intended
    opt-in for Azure staging / prod clones.
    """
    monkeypatch.setenv("WEBSITE_SITE_NAME", "trainsight-app")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("PRAXYS_ENV", raising=False)
    monkeypatch.delenv("PRAXYS_JWT_SECRET", raising=False)
    monkeypatch.delenv("TRAINSIGHT_JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="PRAXYS_JWT_SECRET"):
        auth_secrets.get_jwt_secret()


def test_configured_secret_is_returned_verbatim(monkeypatch):
    monkeypatch.setenv("PRAXYS_JWT_SECRET", "explicit-value")
    assert auth_secrets.get_jwt_secret() == "explicit-value"


def test_configured_secret_is_not_cached(monkeypatch):
    """Operator sets the env var live → next call must pick it up without restart."""
    monkeypatch.delenv("PRAXYS_JWT_SECRET", raising=False)
    monkeypatch.delenv("TRAINSIGHT_JWT_SECRET", raising=False)
    # First call: auto-generated under pytest context.
    generated = auth_secrets.get_jwt_secret()
    # Operator patches the env var. Next call must see it.
    monkeypatch.setenv("PRAXYS_JWT_SECRET", "live-patched")
    assert auth_secrets.get_jwt_secret() == "live-patched"
    assert generated != "live-patched"


def test_explicit_dev_env_allows_generation(monkeypatch):
    """Local dev opts in via PRAXYS_ENV=development."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("PRAXYS_ENV", "development")
    monkeypatch.delenv("PRAXYS_JWT_SECRET", raising=False)
    monkeypatch.delenv("TRAINSIGHT_JWT_SECRET", raising=False)
    secret = auth_secrets.get_jwt_secret()
    assert len(secret) >= 40


def test_generated_secret_is_stable_within_a_process(monkeypatch):
    """Auth.py and users.py must agree on the secret they see."""
    monkeypatch.delenv("PRAXYS_JWT_SECRET", raising=False)
    monkeypatch.delenv("TRAINSIGHT_JWT_SECRET", raising=False)
    first = auth_secrets.get_jwt_secret()
    second = auth_secrets.get_jwt_secret()
    assert first == second
    # Guards against any future regression to a known hardcoded default.
    assert first != "dev-secret-change-in-production!!"
    assert len(first) >= 40


def test_legacy_env_var_still_works(monkeypatch):
    monkeypatch.delenv("PRAXYS_JWT_SECRET", raising=False)
    monkeypatch.setenv("TRAINSIGHT_JWT_SECRET", "legacy-value")
    assert auth_secrets.get_jwt_secret() == "legacy-value"


def test_reset_cache_refuses_outside_pytest(monkeypatch):
    """Runtime code calling this would split-brain workers. Guard it."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    with pytest.raises(RuntimeError, match="pytest"):
        auth_secrets._reset_cache_for_tests()
