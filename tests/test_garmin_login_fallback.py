"""Regression tests for the Garmin CN login fallback.

Background — ``garminconnect`` 0.3.x's mobile / widget login strategies
consume the CAS service ticket against hardcoded ``.com`` hosts
(``mobile.integration.garmin.com``, ``sso.garmin.com/sso/embed``). For
CN accounts those hosts either don't resolve or never set a JWT_WEB
cookie, so the library raises
``GarminConnectAuthenticationError("JWT_WEB cookie not set after ticket
consumption")`` and the chain re-raises on auth errors, never reaching
the portal strategies — which do use the domain-aware
``_portal_service_url`` and work. We catch that specific message and
retry ``_portal_web_login_cffi`` directly.

The sibling DI Bearer token bug (``DI_TOKEN_URL`` hardcoded to ``.com``)
was fixed upstream in garminconnect 0.3.4 (PR #360 — ``_di_token_url``
is now a domain-aware instance attribute), so no DI patching test
coverage lives here.

See ``docs/dev/gotchas.md`` (Garmin CN section) for the full background
and ``scripts/garmin_diagnose.py`` for reproduction tooling.
"""
from __future__ import annotations

import pytest


def _make_client(login_behavior, *, is_cn: bool = True):
    """Build a fake Garmin client where login() runs ``login_behavior``.

    ``login_behavior`` is a zero-arg callable; its return value is the
    login return. Raise to simulate a library failure.
    """
    portal_calls: list[tuple[str, str]] = []
    dump_calls: list[str] = []

    class _FakeInnerClient:
        def __init__(self) -> None:
            self.di_token: str | None = None
            self.jwt_web: str | None = None
            self.cs = object()

        def _portal_web_login_cffi(self, email: str, password: str) -> None:
            portal_calls.append((email, password))

        def dump(self, path: str) -> None:
            dump_calls.append(path)

    class _FakeGarmin:
        def __init__(self) -> None:
            self.is_cn = is_cn
            self.client = _FakeInnerClient()

        def login(self, token_dir: str):
            return login_behavior()

    return _FakeGarmin(), portal_calls, dump_calls


def test_jwt_web_error_falls_back_to_portal_login(tmp_path) -> None:
    """The exact message from the upstream bug must trigger the portal
    fallback with the same credentials passed in."""
    from garminconnect import GarminConnectAuthenticationError
    from api.routes.sync import _login_garmin_with_cn_fallback

    def _raise_jwt_web():
        raise GarminConnectAuthenticationError(
            "JWT_WEB cookie not set after ticket consumption"
        )

    client, portal_calls, dump_calls = _make_client(_raise_jwt_web)
    creds = {"email": "cn-user@example.com", "password": "secret"}

    _login_garmin_with_cn_fallback(client, creds, str(tmp_path / "toks"))

    assert portal_calls == [("cn-user@example.com", "secret")], (
        "JWT_WEB error must trigger _portal_web_login_cffi with the "
        f"same credentials; got {portal_calls!r}"
    )
    assert len(dump_calls) == 1, (
        "After the portal fallback we should attempt one dump() so DI "
        "Bearer tokens persist."
    )


def test_successful_login_does_not_fall_back(tmp_path) -> None:
    """Happy path: when the normal login works, we must not invoke the
    portal strategy a second time (that'd double-authenticate)."""
    from api.routes.sync import _login_garmin_with_cn_fallback

    client, portal_calls, dump_calls = _make_client(lambda: None)
    creds = {"email": "intl-user@example.com", "password": "secret"}

    _login_garmin_with_cn_fallback(client, creds, str(tmp_path / "toks"))

    assert portal_calls == [], (
        "Portal fallback must only run when the normal login raises the "
        f"JWT_WEB error; was called with {portal_calls!r}"
    )
    assert dump_calls == [], (
        "Our code must not call dump() on the success path — the library "
        "already persists tokens inside Garmin.login()."
    )


def test_other_auth_errors_bubble_up(tmp_path) -> None:
    """Real credential failures (wrong password, etc.) must not be
    masked by the portal fallback — the user needs to see them."""
    from garminconnect import GarminConnectAuthenticationError
    from api.routes.sync import _login_garmin_with_cn_fallback

    def _raise_bad_password():
        raise GarminConnectAuthenticationError(
            "401 Unauthorized (Invalid Username or Password)"
        )

    client, portal_calls, _ = _make_client(_raise_bad_password)
    creds = {"email": "x@example.com", "password": "wrong"}

    with pytest.raises(GarminConnectAuthenticationError) as excinfo:
        _login_garmin_with_cn_fallback(
            client, creds, str(tmp_path / "toks"),
        )

    assert "Invalid Username or Password" in str(excinfo.value)
    assert portal_calls == [], (
        "Non-JWT_WEB auth errors must not trigger the portal fallback; "
        f"was called with {portal_calls!r}"
    )
