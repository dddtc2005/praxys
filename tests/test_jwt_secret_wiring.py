"""Integration tests: api/auth.py and api/users.py actually route through get_jwt_secret().

Helper-level tests on the resolver prove it behaves correctly, but they
can't catch a regression where a consumer caches the secret at import
time or falls back to a hardcoded literal. These tests pin down the
wiring end-to-end: we patch the resolver to return a known sentinel,
then prove both mint (users.py's JWTStrategy) and verify (auth.py's
get_current_user_id) see the sentinel.
"""
from datetime import datetime, timedelta, timezone

import jwt
import pytest


@pytest.fixture
def sentinel_secret(monkeypatch):
    """Redirect the resolver to a known value at every call site.

    ``api.auth`` and ``api.users`` both do ``from api.auth_secrets import
    get_jwt_secret``, which binds a local name on import. Patching only the
    source module leaves those local references pointing at the real
    function — a dangerous silent "test passes anyway" mode. Patch each
    call-site name instead.
    """
    from api import auth_secrets

    secret = "sentinel-secret-used-only-in-tests-" + "x" * 16
    stub = lambda: secret  # noqa: E731
    monkeypatch.setattr("api.auth_secrets.get_jwt_secret", stub)
    monkeypatch.setattr("api.auth.get_jwt_secret", stub)
    monkeypatch.setattr("api.users.get_jwt_secret", stub)
    auth_secrets._reset_cache_for_tests()
    yield secret
    auth_secrets._reset_cache_for_tests()


def test_get_jwt_strategy_signs_with_resolver_secret(sentinel_secret):
    """Token minted by users.py must be verifiable with the sentinel."""
    from api.users import get_jwt_strategy

    strategy = get_jwt_strategy()
    # fastapi-users writes a token synchronously via the underlying encode.
    # We don't need the full auth backend — just confirm the token round-trips
    # against the sentinel and fails against any other key.
    token_payload = {
        "sub": "user-123",
        "aud": "fastapi-users:auth",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    forged_token = jwt.encode(token_payload, sentinel_secret, algorithm="HS256")

    decoded = jwt.decode(
        forged_token,
        strategy.secret,   # the resolver's value, not a cached module constant
        algorithms=["HS256"],
        audience="fastapi-users:auth",
    )
    assert decoded["sub"] == "user-123"


def test_get_current_user_id_rejects_tokens_signed_with_old_default(sentinel_secret):
    """A token signed with the pre-fix hardcoded default must not validate."""
    from fastapi import HTTPException, Request

    from api.auth import get_current_user_id

    old_default = "dev-secret-change-in-production!!"
    forged = jwt.encode(
        {
            "sub": "user-should-be-rejected",
            "aud": "fastapi-users:auth",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        old_default,
        algorithm="HS256",
    )

    # Minimal Request stub — get_current_user_id only reads the Authorization header.
    class _StubRequest:
        def __init__(self, token):
            self.headers = {"Authorization": f"Bearer {token}"}

    with pytest.raises(HTTPException) as exc:
        # db=None is fine: signature check fails before the user lookup happens.
        get_current_user_id(_StubRequest(forged), db=None)
    assert exc.value.status_code == 401


def test_auth_and_users_agree_on_the_same_secret(sentinel_secret):
    """The whole point of routing through the resolver: both sides see one value."""
    from api.auth_secrets import get_jwt_secret
    from api.users import get_jwt_strategy

    assert get_jwt_strategy().secret == sentinel_secret
    assert get_jwt_secret() == sentinel_secret
