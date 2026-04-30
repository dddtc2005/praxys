"""Regression tests for the Garmin CN login + DI token patch.

Background — ``garminconnect`` 0.3.x has two CN-breaking holes:

1. ``DI_TOKEN_URL`` is hardcoded to ``diauth.garmin.com``, which has no
   record of CN accounts. Without a DI Bearer token,
   ``connectapi.garmin.cn`` rejects every API call with HTTP 403
   (``ForbiddenException``) — JWT_WEB cookie auth isn't accepted on the
   API gateway. ``diauth.garmin.cn`` is a working parallel service; our
   fix points the exchange there for CN clients.

2. The mobile / widget login strategies consume the CAS service ticket
   against hardcoded ``.com`` hosts (``mobile.integration.garmin.com``,
   ``sso.garmin.com/sso/embed``). That raises
   ``GarminConnectAuthenticationError("JWT_WEB cookie not set after
   ticket consumption")`` and the chain re-raises on auth errors, never
   reaching the portal strategies — which do use the domain-aware
   ``_portal_service_url`` and work. We catch that specific message and
   retry ``_portal_web_login_cffi`` directly.

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
    original_exchange = object()
    original_refresh = object()

    class _FakeInnerClient:
        def __init__(self) -> None:
            self.di_token: str | None = None
            self.jwt_web: str | None = None
            self.cs = object()
            self._exchange_service_ticket = original_exchange
            self._refresh_di_token = original_refresh

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

    return _FakeGarmin(), portal_calls, dump_calls, original_exchange


def test_jwt_web_error_falls_back_to_portal_login(tmp_path) -> None:
    """The exact message from the upstream bug must trigger the portal
    fallback with the same credentials passed in."""
    from garminconnect import GarminConnectAuthenticationError
    from api.routes.sync import _login_garmin_with_cn_fallback

    def _raise_jwt_web():
        raise GarminConnectAuthenticationError(
            "JWT_WEB cookie not set after ticket consumption"
        )

    client, portal_calls, dump_calls, _ = _make_client(_raise_jwt_web)
    creds = {"email": "cn-user@example.com", "password": "secret"}

    _login_garmin_with_cn_fallback(client, creds, str(tmp_path / "toks"))

    assert portal_calls == [("cn-user@example.com", "secret")], (
        "JWT_WEB error must trigger _portal_web_login_cffi with the "
        f"same credentials; got {portal_calls!r}"
    )
    assert len(dump_calls) == 1, (
        "After the portal fallback we should attempt one dump() so DI "
        "Bearer tokens (now possible with the CN DI patch) persist."
    )


def test_successful_login_does_not_fall_back(tmp_path) -> None:
    """Happy path: when the normal login works, we must not invoke the
    portal strategy a second time (that'd double-authenticate)."""
    from api.routes.sync import _login_garmin_with_cn_fallback

    client, portal_calls, dump_calls, _ = _make_client(lambda: None)
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

    client, portal_calls, _, _ = _make_client(_raise_bad_password)
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


def test_cn_client_gets_di_exchange_repointed_to_cn_diauth(tmp_path) -> None:
    """For ``is_cn=True`` clients, the instance-scoped DI exchange
    override must be installed before ``Garmin.login`` runs, so the
    subsequent strategy chain hits ``diauth.garmin.cn`` instead of
    ``diauth.garmin.com`` (the latter has no record of CN accounts)."""
    from api.routes.sync import _login_garmin_with_cn_fallback

    client, _, _, original_exchange = _make_client(
        lambda: None, is_cn=True,
    )
    _login_garmin_with_cn_fallback(
        client, {"email": "cn@example.com", "password": "pw"},
        str(tmp_path / "toks"),
    )

    assert client.client._exchange_service_ticket is not original_exchange, (
        "CN clients must have _exchange_service_ticket overridden so DI "
        "exchange targets diauth.garmin.cn."
    )


def test_international_client_leaves_di_exchange_unchanged(tmp_path) -> None:
    """International (``is_cn=False``) clients must NOT be patched —
    ``diauth.garmin.com`` is the correct DI host for them."""
    from api.routes.sync import _login_garmin_with_cn_fallback

    client, _, _, original_exchange = _make_client(
        lambda: None, is_cn=False,
    )
    _login_garmin_with_cn_fallback(
        client, {"email": "intl@example.com", "password": "pw"},
        str(tmp_path / "toks"),
    )

    assert client.client._exchange_service_ticket is original_exchange, (
        "International clients must keep the library's default DI "
        "exchange (diauth.garmin.com)."
    )


def test_cn_di_patch_sets_and_restores_module_token_url() -> None:
    """Inside the override, the module-level ``DI_TOKEN_URL`` is the CN
    host; after the call returns it's back to the original value. The
    window is serialized by ``_di_token_url_lock`` so concurrent
    international logins that enter their own exchange outside this
    window see the original ``.com`` value. Covers both patched methods:
    ``_exchange_service_ticket`` (login path) and ``_refresh_di_token``
    (token-expiry path)."""
    from garminconnect import client as gc_client
    from api.routes.sync import _patch_cn_di_exchange, _CN_DI_TOKEN_URL

    seen_url: list[tuple[str, str]] = []
    original_url = gc_client.DI_TOKEN_URL

    class _Probe:
        def _exchange_service_ticket(self, ticket, service_url=None):
            # Capture the module-level constant at the moment the real
            # library would read it from its own globals.
            seen_url.append(("exchange", gc_client.DI_TOKEN_URL))

        def _refresh_di_token(self):
            seen_url.append(("refresh", gc_client.DI_TOKEN_URL))

    probe = _Probe()
    _patch_cn_di_exchange(probe)
    probe._exchange_service_ticket("ST-fake", service_url="https://x/app")
    probe._refresh_di_token()

    assert seen_url == [
        ("exchange", _CN_DI_TOKEN_URL),
        ("refresh", _CN_DI_TOKEN_URL),
    ], (
        "Both patched methods must see DI_TOKEN_URL rebound to the CN "
        f"host during the call; got {seen_url!r}"
    )
    assert gc_client.DI_TOKEN_URL == original_url, (
        "DI_TOKEN_URL must be restored to the original .com value after "
        f"the call; got {gc_client.DI_TOKEN_URL!r}"
    )


def test_cn_di_patch_restores_token_url_when_exchange_raises() -> None:
    """If the patched ``_exchange_service_ticket`` raises, the
    ``finally`` must still restore ``DI_TOKEN_URL`` to its original
    value. Without this, a single transient DI exchange failure would
    poison every subsequent login in the process until a fresh patch
    runs."""
    from garminconnect import client as gc_client
    from api.routes.sync import _patch_cn_di_exchange

    original_url = gc_client.DI_TOKEN_URL

    class _Probe:
        def _exchange_service_ticket(self, ticket, service_url=None):
            raise RuntimeError("simulated DI exchange failure")

        def _refresh_di_token(self):
            pass

    probe = _Probe()
    _patch_cn_di_exchange(probe)

    with pytest.raises(RuntimeError, match="simulated DI exchange failure"):
        probe._exchange_service_ticket("ST-fake")

    assert gc_client.DI_TOKEN_URL == original_url, (
        "DI_TOKEN_URL must be restored even when the inner call raises; "
        f"got {gc_client.DI_TOKEN_URL!r}"
    )


def test_cn_patch_is_installed_before_login_runs(tmp_path) -> None:
    """Invariant: for CN clients, ``_patch_cn_di_exchange`` must run
    *before* ``client.login()`` — the very first strategy the library
    tries goes through ``_exchange_service_ticket``, so patching after
    login would send the first-attempt ticket to ``diauth.garmin.com``
    and reproduce issue #75's 403 symptom while all other CN tests
    continued to pass. This test would have caught the first-iteration
    of the fix where the DI patch wasn't yet in place."""
    from api.routes.sync import _login_garmin_with_cn_fallback

    sentinel = object()
    observed: list[object] = []

    class _FakeInner:
        def __init__(self) -> None:
            self._exchange_service_ticket = sentinel
            self._refresh_di_token = sentinel

        def _portal_web_login_cffi(self, email: str, password: str) -> None:
            pass

        def dump(self, path: str) -> None:
            pass

    class _FakeGarmin:
        is_cn = True

        def __init__(self) -> None:
            self.client = _FakeInner()

        def login(self, path: str) -> None:
            # Snapshot at login time — if the patch ran first, the
            # sentinel is gone.
            observed.append(self.client._exchange_service_ticket)

    client = _FakeGarmin()
    _login_garmin_with_cn_fallback(
        client, {"email": "cn@example.com", "password": "pw"},
        str(tmp_path / "toks"),
    )

    assert observed and observed[0] is not sentinel, (
        "CN DI patch must be installed before Garmin.login() runs so the "
        "first login strategy's DI exchange hits diauth.garmin.cn."
    )
