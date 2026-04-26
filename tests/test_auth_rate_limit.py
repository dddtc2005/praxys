"""Tests for the auth-endpoint rate limiter (api/auth_rate_limit.py).

Two layers of coverage:

- ``_SlidingWindow`` is exercised directly with a stubbed clock so the
  window-rollover and LRU-eviction paths run without real sleeps.
- The full ASGI middleware is exercised through a tiny FastAPI app
  (mirrors api/main.py wiring without depending on the auth machinery)
  to verify per-path bucketing, per-IP bucketing via X-Forwarded-For,
  the 429 body, and the Retry-After header.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.auth_rate_limit import (
    AuthRateLimitMiddleware,
    DEFAULT_LIMITS,
    _SlidingWindow,
    _client_ip,
    _normalize_path,
    _parse_xff_entry,
    is_rate_limit_disabled,
)


# ---------------------------------------------------------------------------
# _SlidingWindow unit tests
# ---------------------------------------------------------------------------


def test_sliding_window_allows_under_limit():
    win = _SlidingWindow(limit=3, window_secs=60, max_clients=10)
    for _ in range(3):
        allowed, retry = win.check_and_record("ip-a")
        assert allowed is True
        assert retry == 0


def test_sliding_window_blocks_at_limit_with_bounded_retry_after():
    win = _SlidingWindow(limit=2, window_secs=60, max_clients=10)
    win.check_and_record("ip-a")
    win.check_and_record("ip-a")
    allowed, retry = win.check_and_record("ip-a")
    assert allowed is False
    # Retry-After is bounded above by the window length plus a 1-second
    # rounding margin; below by 1 (we never advise the client to retry
    # immediately when blocked).
    assert 1 <= retry <= 61


def test_sliding_window_separates_keys():
    win = _SlidingWindow(limit=1, window_secs=60, max_clients=10)
    assert win.check_and_record("ip-a") == (True, 0)
    assert win.check_and_record("ip-b") == (True, 0)
    assert win.check_and_record("ip-a")[0] is False


def test_sliding_window_evicts_old_entries(monkeypatch):
    """Once timestamps fall outside the window, capacity is restored."""
    fake_now = [1000.0]
    monkeypatch.setattr(
        "api.auth_rate_limit.time.monotonic", lambda: fake_now[0]
    )
    win = _SlidingWindow(limit=2, window_secs=10, max_clients=10)
    win.check_and_record("ip-a")
    win.check_and_record("ip-a")
    assert win.check_and_record("ip-a")[0] is False
    fake_now[0] += 11  # roll past the window
    assert win.check_and_record("ip-a") == (True, 0)


def test_sliding_window_lru_evicts_least_recent_and_tracks_recency():
    """Inserting beyond ``max_clients`` removes the least-recently-used
    bucket; touching an existing key promotes it via ``move_to_end`` so
    a different key gets evicted on the next overflow."""
    win = _SlidingWindow(limit=10, window_secs=60, max_clients=2)
    win.check_and_record("ip-a")
    win.check_and_record("ip-b")
    win.check_and_record("ip-c")  # forces eviction of the LRU (ip-a)
    assert "ip-a" not in win._buckets
    assert list(win._buckets.keys()) == ["ip-b", "ip-c"]

    # Touching ip-b promotes it; ip-c is now the LRU and must be evicted
    # when ip-d arrives.
    win.check_and_record("ip-b")
    assert list(win._buckets.keys()) == ["ip-c", "ip-b"]
    win.check_and_record("ip-d")
    assert list(win._buckets.keys()) == ["ip-b", "ip-d"]


@pytest.mark.parametrize(
    "limit,window,max_clients",
    [
        (0, 60, 10),
        (1, 0, 10),
        (1, 60, 0),
        (-1, 60, 10),
    ],
)
def test_sliding_window_rejects_nonpositive_args(limit, window, max_clients):
    """A misconfigured window would fail silently (limit=0 → always block;
    max_clients=0 → every bucket evicted on insert). Better to refuse to
    construct it at all."""
    with pytest.raises(ValueError):
        _SlidingWindow(limit=limit, window_secs=window, max_clients=max_clients)


# ---------------------------------------------------------------------------
# _parse_xff_entry / _client_ip unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1.2.3.4", "1.2.3.4"),
        ("1.2.3.4:443", "1.2.3.4"),
        ("2001:db8::1", "2001:db8::1"),
        ("[2001:db8::1]:443", "2001:db8::1"),
        ("[::1]", "::1"),
        ("  2001:db8::1  ", "2001:db8::1"),
    ],
)
def test_parse_xff_entry_accepts_valid_forms(raw, expected):
    assert _parse_xff_entry(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "not-an-ip",
        "real-1.2.3.4",
        "1.2.3.4.5",
        "[2001:db8::1",  # missing closing bracket
        ":::",
    ],
)
def test_parse_xff_entry_rejects_invalid(raw):
    assert _parse_xff_entry(raw) is None


def _scope_with_xff(xff_value: bytes) -> dict:
    return {
        "type": "http",
        "headers": [(b"x-forwarded-for", xff_value)],
        "client": ("127.0.0.1", 50000),
    }


def test_client_ip_trusts_rightmost_by_default(monkeypatch):
    monkeypatch.delenv("PRAXYS_TRUSTED_PROXY_HOPS", raising=False)
    scope = _scope_with_xff(b"203.0.113.7, 198.51.100.42")
    assert _client_ip(scope) == "198.51.100.42"


def test_client_ip_strips_ipv4_port_suffix(monkeypatch):
    monkeypatch.delenv("PRAXYS_TRUSTED_PROXY_HOPS", raising=False)
    assert _client_ip(_scope_with_xff(b"5.6.7.8:443")) == "5.6.7.8"


def test_client_ip_handles_bare_ipv6(monkeypatch):
    """Bare IPv6 must NOT be split on the first colon — that bug would
    collapse every IPv6 client into a single "2001" bucket."""
    monkeypatch.delenv("PRAXYS_TRUSTED_PROXY_HOPS", raising=False)
    assert _client_ip(_scope_with_xff(b"2001:db8::1")) == "2001:db8::1"


def test_client_ip_handles_bracketed_ipv6_with_port(monkeypatch):
    monkeypatch.delenv("PRAXYS_TRUSTED_PROXY_HOPS", raising=False)
    assert _client_ip(_scope_with_xff(b"[2001:db8::1]:443")) == "2001:db8::1"


def test_client_ip_falls_back_to_scope_client_when_xff_invalid(monkeypatch, caplog):
    monkeypatch.delenv("PRAXYS_TRUSTED_PROXY_HOPS", raising=False)
    scope = _scope_with_xff(b"garbage-not-an-ip")
    scope["client"] = ("9.9.9.9", 1)
    with caplog.at_level("WARNING", logger="api.auth_rate_limit"):
        assert _client_ip(scope) == "9.9.9.9"
    assert any(
        "unparseable XFF entry" in r.message for r in caplog.records
    )


def test_client_ip_falls_back_to_scope_client_when_xff_absent():
    scope = {"type": "http", "headers": [], "client": ("9.9.9.9", 50000)}
    assert _client_ip(scope) == "9.9.9.9"


def test_client_ip_respects_proxy_hops(monkeypatch):
    monkeypatch.setenv("PRAXYS_TRUSTED_PROXY_HOPS", "2")
    scope = _scope_with_xff(b"203.0.113.7, 198.51.100.42, 192.0.2.5")
    # With 2 trusted hops we walk one entry left of the rightmost.
    assert _client_ip(scope) == "198.51.100.42"


def test_client_ip_zero_hops_ignores_xff(monkeypatch):
    monkeypatch.setenv("PRAXYS_TRUSTED_PROXY_HOPS", "0")
    scope = _scope_with_xff(b"1.2.3.4, 5.6.7.8")
    scope["client"] = ("9.9.9.9", 1)
    assert _client_ip(scope) == "9.9.9.9"


def test_client_ip_logs_warning_on_malformed_hops(monkeypatch, caplog):
    monkeypatch.setenv("PRAXYS_TRUSTED_PROXY_HOPS", "two")
    scope = _scope_with_xff(b"203.0.113.7, 198.51.100.42")
    with caplog.at_level("WARNING", logger="api.auth_rate_limit"):
        # Falls back to hops=1 → rightmost entry.
        assert _client_ip(scope) == "198.51.100.42"
    assert any(
        "PRAXYS_TRUSTED_PROXY_HOPS" in r.message for r in caplog.records
    )


# ---------------------------------------------------------------------------
# _normalize_path unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("/api/auth/login", "/api/auth/login"),
        ("/api/auth/login/", "/api/auth/login"),
        ("/api/auth/login///", "/api/auth/login"),
        ("/", "/"),
        ("", ""),
    ],
)
def test_normalize_path(raw, expected):
    assert _normalize_path(raw) == expected


# ---------------------------------------------------------------------------
# DEFAULT_LIMITS immutability
# ---------------------------------------------------------------------------


def test_default_limits_is_immutable():
    """A stray import-time mutation of the module-level limits dict
    would silently weaken every subsequently-instantiated middleware.
    The MappingProxyType wrapper closes that hole."""
    with pytest.raises(TypeError):
        DEFAULT_LIMITS["/api/auth/login"] = (10000, 1)  # type: ignore[index]


# ---------------------------------------------------------------------------
# Middleware integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
def rl_client():
    """Tiny FastAPI app that mirrors api/main.py wiring of the limiter.

    The handlers are stubs so the test isolates the middleware's behavior
    from real auth, DB, or WeChat code paths.
    """
    app = FastAPI()
    app.add_middleware(
        AuthRateLimitMiddleware,
        limits={
            "/api/auth/login": (3, 60),
            "/api/auth/register": (2, 60),
        },
    )

    @app.post("/api/auth/login")
    async def _login_stub():
        return {"ok": True}

    @app.post("/api/auth/register")
    async def _register_stub():
        return {"ok": True}

    @app.get("/api/health")
    async def _health_stub():
        return {"ok": True}

    return TestClient(app)


def _xff(ip: str) -> dict:
    return {"X-Forwarded-For": ip}


def test_middleware_allows_under_limit(rl_client):
    for _ in range(3):
        r = rl_client.post("/api/auth/login", headers=_xff("198.51.100.1"))
        assert r.status_code == 200, r.text


def test_middleware_blocks_with_retry_after(rl_client):
    for _ in range(3):
        rl_client.post("/api/auth/login", headers=_xff("198.51.100.1"))
    blocked = rl_client.post("/api/auth/login", headers=_xff("198.51.100.1"))
    assert blocked.status_code == 429
    payload = blocked.json()
    assert payload["detail"] == "AUTH_RATE_LIMITED"
    assert 1 <= payload["retry_after"] <= 61
    assert int(blocked.headers["retry-after"]) >= 1
    assert blocked.headers["content-type"].startswith("application/json")


def test_middleware_separates_ips(rl_client):
    """Different X-Forwarded-For values get independent buckets."""
    for _ in range(3):
        rl_client.post("/api/auth/login", headers=_xff("198.51.100.1"))
    assert rl_client.post("/api/auth/login", headers=_xff("198.51.100.1")).status_code == 429
    assert rl_client.post("/api/auth/login", headers=_xff("203.0.113.2")).status_code == 200


def test_middleware_separates_paths(rl_client):
    """A login bucket exhaustion does not block a register attempt."""
    for _ in range(3):
        rl_client.post("/api/auth/login", headers=_xff("198.51.100.1"))
    assert rl_client.post("/api/auth/login", headers=_xff("198.51.100.1")).status_code == 429
    # Register has its own bucket and limit (2).
    assert rl_client.post("/api/auth/register", headers=_xff("198.51.100.1")).status_code == 200


def test_middleware_normalizes_trailing_slash(rl_client):
    """`/api/auth/login` and `/api/auth/login/` share one bucket so an
    attacker can't bypass the limiter by appending a slash."""
    for _ in range(3):
        rl_client.post("/api/auth/login/", headers=_xff("198.51.100.1"))
    blocked = rl_client.post("/api/auth/login", headers=_xff("198.51.100.1"))
    assert blocked.status_code == 429


def test_middleware_separates_ipv6_from_ipv4(rl_client):
    """The IPv6 parser fix is load-bearing: without it `2001:db8::1`
    would be truncated to `2001` and bucket alongside everyone else's
    truncated IPv6."""
    for _ in range(3):
        rl_client.post("/api/auth/login", headers=_xff("2001:db8::1"))
    # IPv4 client must still be able to log in.
    assert rl_client.post("/api/auth/login", headers=_xff("198.51.100.1")).status_code == 200
    # And a *different* IPv6 client must too — they parsed to a distinct
    # bucket, which would not have been the case under the old split-on-":".
    assert rl_client.post("/api/auth/login", headers=_xff("2001:db8::2")).status_code == 200


def test_middleware_ignores_unconfigured_paths(rl_client):
    """Health is not in the limits dict; never rate-limited."""
    for _ in range(20):
        r = rl_client.get("/api/health", headers=_xff("198.51.100.1"))
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Disable flag
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on", "  true  "])
def test_disable_flag_recognizes_truthy_values(monkeypatch, value):
    monkeypatch.setenv("PRAXYS_AUTH_RATE_LIMIT_DISABLED", value)
    assert is_rate_limit_disabled() is True


@pytest.mark.parametrize("value", ["", "false", "0", "no"])
def test_disable_flag_recognizes_falsy_values(monkeypatch, value):
    monkeypatch.setenv("PRAXYS_AUTH_RATE_LIMIT_DISABLED", value)
    assert is_rate_limit_disabled() is False
