"""Per-IP sliding-window rate limiter for the authentication surface.

Why this module exists
----------------------
Praxys is open-source on GitHub. Anyone can read api/routes/register.py,
api/routes/wechat.py, and the FastAPI-Users login route to learn the
exact request shapes. This middleware caps per-IP attempts on the auth
surface so credential-stuffing and invitation-code-bruteforcing become
infeasible, even though the endpoint contracts are public.

Endpoints covered
-----------------
- /api/auth/login                       (FastAPI-Users JWT login)
- /api/auth/register                    (custom invite-aware register)
- /api/auth/wechat/login
- /api/auth/wechat/register
- /api/auth/wechat/link-with-password

Implementation notes
--------------------
- In-memory sliding window per ``(path, client_ip)``, backed by a deque
  of monotonic timestamps. The bucket ``OrderedDict`` is LRU-bounded so a
  malicious enumerator cannot OOM the worker.
- Per-process state. With N gunicorn workers the effective ceiling is
  N × the configured value — acceptable as defense against unsophisticated
  brute force, not a sophisticated DoS. Move to a Redis-backed limiter
  if cross-worker enforcement matters.
- Client-IP resolution trusts the *rightmost* X-Forwarded-For entry. The
  leftmost is client-controlled (forgeable); the rightmost is what the
  immediate upstream proxy observed and is therefore safe on a single-hop
  Azure App Service deployment. ``PRAXYS_TRUSTED_PROXY_HOPS`` lets an
  operator walk further left when the proxy chain is longer (e.g.
  Front Door → App Service).
- Disable entirely with ``PRAXYS_AUTH_RATE_LIMIT_DISABLED=true`` for
  tests / local dev.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import threading
import time
from collections import OrderedDict, deque
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Mapping, MutableMapping

logger = logging.getLogger(__name__)

# ASGI-style aliases so this file doesn't pull starlette.types into a
# hot path. Matches the shapes Starlette/uvicorn pass through.
Scope = MutableMapping[str, Any]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[..., Awaitable[None]]

# (max_requests, window_seconds) per path. Tuned for a small user base:
# tight enough that brute force is infeasible, loose enough that a real
# user fat-fingering "login" doesn't get locked out for the day. Wrapped
# in MappingProxyType so a stray import-time mutation can't silently
# weaken the limiter.
_DEFAULT_LIMITS_RAW: dict[str, tuple[int, int]] = {
    "/api/auth/login":                       (10, 5 * 60),
    "/api/auth/register":                    (5, 60 * 60),
    "/api/auth/wechat/login":                (30, 5 * 60),
    "/api/auth/wechat/link-with-password":   (10, 15 * 60),
    "/api/auth/wechat/register":             (5, 60 * 60),
}
DEFAULT_LIMITS: Mapping[str, tuple[int, int]] = MappingProxyType(
    _DEFAULT_LIMITS_RAW
)

_DEFAULT_MAX_TRACKED_CLIENTS = 10_000


class _SlidingWindow:
    """Per-key bounded deque of recent request timestamps."""

    __slots__ = ("limit", "window_secs", "_buckets", "_lock", "_max_clients")

    def __init__(self, limit: int, window_secs: int, max_clients: int):
        if limit < 1 or window_secs < 1 or max_clients < 1:
            raise ValueError(
                "_SlidingWindow requires limit>=1, window_secs>=1, "
                f"max_clients>=1; got limit={limit}, "
                f"window_secs={window_secs}, max_clients={max_clients}"
            )
        self.limit = limit
        self.window_secs = window_secs
        self._buckets: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()
        self._max_clients = max_clients

    def check_and_record(self, key: str) -> tuple[bool, int]:
        """Return ``(allowed, retry_after_seconds)``.

        ``retry_after_seconds`` is 0 when the call is allowed, and the
        smallest integer wait for the oldest in-window entry to expire
        when blocked.
        """
        now = time.monotonic()
        cutoff = now - self.window_secs
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = deque()
                self._buckets[key] = bucket
            else:
                self._buckets.move_to_end(key)
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                oldest = bucket[0]
                retry = int(oldest + self.window_secs - now) + 1
                return False, max(1, retry)
            bucket.append(now)
            while len(self._buckets) > self._max_clients:
                self._buckets.popitem(last=False)
        return True, 0


def _parse_xff_entry(raw: str) -> str | None:
    """Extract a normalized IP from a single X-Forwarded-For entry.

    Handles four shapes seen in the wild:
        "1.2.3.4"             — bare IPv4
        "1.2.3.4:443"         — IPv4 with port
        "2001:db8::1"         — bare IPv6
        "[2001:db8::1]:443"   — bracketed IPv6 with port (RFC 7239)

    Returns ``None`` for unparseable input so the caller can choose a
    safe fallback (the ASGI socket peer) instead of conflating every
    bad-XFF caller into a single bucket.
    """
    e = raw.strip()
    if not e:
        return None
    if e.startswith("["):
        end = e.find("]")
        if end > 0:
            e = e[1:end]
        else:
            return None
    elif e.count(":") == 1:
        e = e.split(":", 1)[0]
    try:
        ipaddress.ip_address(e)
    except ValueError:
        return None
    return e


def _client_ip(scope: Scope) -> str:
    """Best-effort client IP for rate-limit bucketing.

    Trusts the rightmost X-Forwarded-For entry — that's what the immediate
    upstream proxy observed and is the safe choice on Azure App Service
    (single proxy hop). Leftmost entries are client-controlled and
    forgeable. Tune ``PRAXYS_TRUSTED_PROXY_HOPS`` to walk further left when
    the proxy chain is fixed and longer.

    Falls back to the ASGI socket peer if XFF is absent, malformed, or
    parses to an invalid IP. We deliberately do *not* fall back to a
    shared sentinel like ``"unknown"`` — that would conflate every
    bad-XFF caller into a single bucket and let one misbehaving upstream
    lock out every legitimate client.
    """
    raw_hops = os.environ.get("PRAXYS_TRUSTED_PROXY_HOPS", "1")
    try:
        hops = max(0, int(raw_hops))
    except ValueError:
        logger.warning(
            "PRAXYS_TRUSTED_PROXY_HOPS=%r is not an int; defaulting to 1",
            raw_hops,
        )
        hops = 1

    if hops > 0:
        for name, value in scope.get("headers", ()):
            if name == b"x-forwarded-for":
                entries = [
                    e for e in (
                        s.strip() for s in value.decode("latin-1").split(",")
                    )
                    if e
                ]
                if entries:
                    idx = max(0, len(entries) - hops)
                    parsed = _parse_xff_entry(entries[idx])
                    if parsed:
                        return parsed
                    logger.warning(
                        "rate-limit: unparseable XFF entry %r; "
                        "falling back to ASGI socket peer",
                        entries[idx],
                    )
                break

    client = scope.get("client")
    return client[0] if client else "unknown"


async def _send_429(send: Send, retry_after: int) -> None:
    """Emit a 429 with a JSON body and Retry-After header.

    Swallows the narrow set of exceptions raised when the client
    disconnects mid-response — the throttle is already recorded; no need
    to bubble a teardown error up through Starlette's error logger.
    """
    body = (
        b'{"detail":"AUTH_RATE_LIMITED","retry_after":'
        + str(retry_after).encode()
        + b"}"
    )
    headers = [
        (b"content-type", b"application/json"),
        (b"retry-after", str(retry_after).encode()),
        (b"content-length", str(len(body)).encode()),
    ]
    try:
        await send({"type": "http.response.start", "status": 429, "headers": headers})
        await send({"type": "http.response.body", "body": body})
    except (OSError, RuntimeError, asyncio.CancelledError) as exc:
        logger.debug("client disconnected before 429 sent: %s", exc)


def _normalize_path(path: str) -> str:
    """Strip a single trailing slash so ``/api/auth/login`` and
    ``/api/auth/login/`` map to the same window. The root ``/`` is kept
    as-is so we don't collapse it to an empty string."""
    return path.rstrip("/") or path


class AuthRateLimitMiddleware:
    """ASGI middleware enforcing per-path per-IP auth rate limits.

    Only HTTP requests whose (normalized) path matches a configured
    limit are inspected; all other traffic short-circuits with a single
    dict lookup.
    """

    def __init__(
        self,
        app: ASGIApp,
        limits: Mapping[str, tuple[int, int]] | None = None,
        max_tracked_clients: int = _DEFAULT_MAX_TRACKED_CLIENTS,
    ):
        self.app = app
        effective = limits if limits is not None else DEFAULT_LIMITS
        self._windows: dict[str, _SlidingWindow] = {
            _normalize_path(path): _SlidingWindow(limit, window, max_tracked_clients)
            for path, (limit, window) in effective.items()
        }
        logger.info(
            "AuthRateLimitMiddleware enabled for: %s",
            sorted(self._windows),
        )

    async def __call__(self, scope: Scope, receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        path = _normalize_path(scope.get("path", ""))
        window = self._windows.get(path)
        if window is None:
            await self.app(scope, receive, send)
            return
        ip = _client_ip(scope)
        allowed, retry_after = window.check_and_record(ip)
        if allowed:
            await self.app(scope, receive, send)
            return
        logger.warning(
            "auth rate limit hit ip=%s path=%s retry_after=%ds",
            ip, path, retry_after,
        )
        await _send_429(send, retry_after)


def is_rate_limit_disabled() -> bool:
    """True when ``PRAXYS_AUTH_RATE_LIMIT_DISABLED`` opts out (tests, dev)."""
    return os.environ.get("PRAXYS_AUTH_RATE_LIMIT_DISABLED", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
