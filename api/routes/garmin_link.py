"""Interactive Garmin login — server-side browser with viewport relay.

## The problem this solves

Garmin's bot model treats Azure App Service IPs as suspicious and gates
fresh SSO logins from those IPs behind ``CAPTCHA_REQUIRED``. The
``garminconnect`` library has no way to satisfy that gate from a
headless context — the Cloudflare Turnstile widget needs human
interaction. Once a user has cached DI Bearer tokens, the refresh path
through ``connectapi.garmin.com`` is unaffected and works fine; the
CAPTCHA only blocks the *initial* token acquisition. So the fix is to
do that one acquisition through a browser whose HTTP traffic
originates from our IP — but with a real human in the loop to clear
the gate.

## How it works

1. User clicks "Use Interactive Login" on Settings → frontend POSTs
   to ``/api/settings/connections/garmin/interactive`` with email +
   password + is_cn.
2. Backend spins a sync Playwright Chromium in a daemon thread,
   navigates to Garmin's portal sign-in URL, autotypes the credentials,
   and waits for the user to complete CAPTCHA / MFA. Each session
   has its own thread + browser context so multiple users in flight
   don't collide.
3. Frontend opens a WebSocket to ``/...interactive/{session_id}/ws``;
   backend streams JPEG screenshots at 5 fps and accepts click/keyboard
   events. The browser HTTP traffic to ``sso.garmin.com`` originates
   from our App Service IP — that's the whole point.
4. When the page lands on ``connect.garmin.com/modern/`` the backend
   detects login success, drives the page to issue a connectapi.* call
   so it can capture the resulting ``Authorization: Bearer <DI>`` and
   ``di_refresh_token`` from network traffic, and writes those into
   ``garmin_tokens.json`` exactly as ``Garmin.dump()`` would.
5. Backend stores the email/password in the encrypted creds blob (so
   subsequent expired-token re-logins can attempt password auth before
   asking the user for another interactive solve), resets the
   connection's backoff state, and tells the WS client we're done.

## Why this isn't in the regular sync path

Spinning a Chromium per user isn't free — ~300MB RAM, ~5s cold start.
We only do it when the headless flow fails with a CAPTCHA gate, and
we cap concurrent sessions to keep App Service B-tier from OOM. Once
tokens are issued, all routine syncs go back to the cheap
``connectapi.garmin.com`` path.
"""
from __future__ import annotations

import asyncio
import base64
import json as json_mod
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from api.auth import require_write_access
# Don't import SessionLocal as a name — db.session lazily assigns it
# inside init_db(), and a top-level ``from db.session import SessionLocal``
# would freeze the value at this module's import time (often ``None``
# under pytest collection). Always reach into the live module to get
# the current sessionmaker.
from db import session as db_session


logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Cap concurrent interactive sessions. Each one holds a Chromium process
# (~300MB) and a daemon thread; on App Service B1 (1.75GB) we can't host
# more than a few alongside the API workers + scheduler.
MAX_CONCURRENT_SESSIONS = 3

# How long to keep a session alive without activity before we tear it
# down. Generous because some users take time on CAPTCHA + MFA.
SESSION_TTL_SECONDS = 600  # 10 minutes

# Viewport size to drive Playwright at. Garmin's responsive design works
# at desktop widths; mobile layouts add complexity for click coordinates.
VIEWPORT_WIDTH = 1024
VIEWPORT_HEIGHT = 768

# Frame rate / quality for the relay. 5 fps is plenty for filling a form;
# JPEG 65% balances size against legibility of CAPTCHA images.
RELAY_FPS = 5
JPEG_QUALITY = 65


# ---------------------------------------------------------------------------
# Browser bootstrap
# ---------------------------------------------------------------------------

def _browsers_path() -> Path:
    """Where Playwright's Chromium binaries live.

    Default Playwright location is ``~/.cache/ms-playwright``; on Azure
    App Service ``$HOME`` resolves to ``/home``, which IS persisted
    across restarts (it's the shared Azure Files mount), so the install
    survives. We make it explicit so dev-mode and prod agree.
    """
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override:
        return Path(override)
    return Path.home() / ".cache" / "ms-playwright"


_chromium_install_lock = threading.Lock()
_chromium_installed = False


def _ensure_chromium_installed() -> None:
    """Idempotent: install Chromium if not yet present.

    The ``playwright`` Python package ships with the SDK but not the
    browser binaries — those come from a separate ``playwright install
    chromium`` step. We don't bake that into the deploy workflow because
    the OG-card render is the only other Playwright user and it runs
    on dev machines, not App Service. So the first interactive-login
    attempt eats the ~30s install cost; subsequent ones see it cached.
    """
    global _chromium_installed
    if _chromium_installed:
        return
    with _chromium_install_lock:
        if _chromium_installed:
            return

        path = _browsers_path()
        if path.exists() and any(path.glob("chromium-*")):
            _chromium_installed = True
            return

        logger.info("Installing Playwright Chromium (one-time)…")
        env = os.environ.copy()
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(path)
        # No --with-deps: that requires apt install + root, which the
        # App Service sandbox doesn't grant. App Service Linux ships
        # most of Chromium's runtime libs in the base image; missing
        # ones will surface as a launch error, which we surface to
        # the user via the WS error event.
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            logger.error(
                "Playwright Chromium install failed: stdout=%s stderr=%s",
                result.stdout, result.stderr,
            )
            raise RuntimeError(
                "Failed to install Chromium for interactive login. "
                f"Exit {result.returncode}: {result.stderr[:500]}"
            )
        _chromium_installed = True
        logger.info("Playwright Chromium installed at %s", path)


# ---------------------------------------------------------------------------
# Session model
# ---------------------------------------------------------------------------

@dataclass
class _Session:
    """One Playwright session driving Garmin's login flow.

    Owned by a single daemon thread that runs the browser; the API
    handlers and WebSocket endpoint communicate with it via the queues
    and the ``state`` flag. We never touch Playwright objects from any
    thread other than the owner — sync Playwright is decidedly not
    threadsafe.
    """

    id: str
    user_id: str
    email: str
    password: str
    is_cn: bool
    created_at: datetime = field(default_factory=datetime.utcnow)
    state: str = "starting"  # starting | ready | succeeded | failed | closed
    error_message: str | None = None
    captured_tokens: dict | None = None

    # Email/password actually submitted to ``sso.garmin.com/portal/api/login``,
    # captured via Playwright's request listener. May differ from the
    # email/password the user POSTed to ``/interactive`` if they edited
    # the inputs in the relayed viewport (e.g. fixed a typo). Empty
    # until the form is submitted; ``_persist_captured_tokens`` prefers
    # this over ``email``/``password`` so the encrypted creds blob
    # always reflects what Garmin actually accepted.
    submitted_email: str | None = None
    submitted_password: str | None = None

    # Cross-thread channels — both threadsafe ``queue.Queue`` so the
    # Playwright owner thread (sync) and the WS coroutine (async) can
    # produce/consume on opposite ends without an event loop binding.
    # ``frame_queue`` carries server→client messages (bounded to keep
    # a slow client from leaking memory); ``input_queue`` carries
    # client→server events.
    frame_queue: "queue.Queue[dict]" = field(
        default_factory=lambda: queue.Queue(maxsize=8)
    )
    input_queue: "queue.Queue[dict]" = field(
        default_factory=lambda: queue.Queue(maxsize=64)
    )

    # Set by the WS handler to signal an explicit cancel from the user.
    cancel_event: threading.Event = field(default_factory=threading.Event)


_sessions: dict[str, _Session] = {}
_sessions_lock = threading.Lock()


def _gc_sessions() -> None:
    """Drop sessions past their TTL or in a terminal state for >1min."""
    now = datetime.utcnow()
    expired = []
    with _sessions_lock:
        for sid, sess in list(_sessions.items()):
            age = (now - sess.created_at).total_seconds()
            terminal = sess.state in ("succeeded", "failed", "closed")
            if age > SESSION_TTL_SECONDS or (terminal and age > 60):
                expired.append(sid)
        for sid in expired:
            sess = _sessions.pop(sid, None)
            if sess:
                sess.cancel_event.set()


# ---------------------------------------------------------------------------
# Browser worker (runs on its own thread)
# ---------------------------------------------------------------------------

# Garmin's domain-aware service URL. The sso host swaps .com↔.cn but the
# CAS service URL must match — the library uses this same pattern.
def _portal_signin_url(is_cn: bool) -> str:
    domain = "garmin.cn" if is_cn else "garmin.com"
    service = f"https://connect.{domain}/app"
    return (
        f"https://sso.{domain}/portal/sso/en-US/sign-in"
        f"?clientId=GarminConnect&service={service}"
    )


# Successful login lands on connect.garmin.{com,cn}/modern/, possibly
# after a few intermediate redirects. We watch URLs as they change.
_SUCCESS_URL_RE = re.compile(r"https?://connect\.garmin\.(com|cn)/modern", re.I)


def _run_browser_session(session: _Session) -> None:
    """Owner thread for one interactive login.

    Drives Playwright synchronously: navigates, autotypes credentials,
    streams frames into ``session.frame_queue``, applies inputs from
    ``session.input_queue``, and on successful navigation captures the
    DI tokens off the page's network traffic before persisting them.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        logger.exception("Playwright import failed for session %s", session.id)
        session.state = "failed"
        session.error_message = f"Playwright unavailable: {exc}"
        return

    captured_tokens: dict[str, Any] = {}

    with sync_playwright() as p:
        browser = None
        try:
            os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_browsers_path())
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            context = browser.new_context(
                viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )

            # Hook the DI Bearer / refresh exchange. After the user
            # completes the CAS flow, Garmin's web app calls
            # diauth.garmin.{com,cn}/di-oauth2-service/oauth/token
            # with the service ticket; the response contains the
            # access_token + refresh_token + client_id we need to
            # persist. Listening on the response is the cleanest
            # capture — we don't have to inject JS into the page.
            def _on_response(response):
                url = response.url
                if "/di-oauth2-service/oauth/token" in url:
                    try:
                        body = response.json()
                    except Exception:
                        return
                    access = body.get("access_token")
                    refresh = body.get("refresh_token")
                    if not access:
                        return
                    captured_tokens["di_token"] = access
                    if refresh:
                        captured_tokens["di_refresh_token"] = refresh
                    # client_id often comes back as an explicit field;
                    # if not, decode it from the JWT payload (the lib
                    # does the same fallback in _extract_client_id_from_jwt).
                    cid = body.get("client_id")
                    if not cid:
                        cid = _decode_jwt_client_id(access)
                    if cid:
                        captured_tokens["di_client_id"] = cid
                    logger.info(
                        "Captured DI tokens for session %s (client_id=%s, has_refresh=%s)",
                        session.id, cid, bool(refresh),
                    )

            context.on("response", _on_response)

            # Capture the credentials *actually* submitted to Garmin so a
            # user who corrects a typo in the relayed viewport doesn't
            # leave us persisting their original (rejected) password —
            # which would silently break refresh-token-expiry password
            # auth ~30 days later. The portal form POSTs to
            # /portal/api/login with {"username", "password", ...} JSON.
            def _on_request(request):
                if "/portal/api/login" not in request.url:
                    return
                if request.method != "POST":
                    return
                try:
                    body = json_mod.loads(request.post_data or "{}")
                except Exception:
                    return
                username = body.get("username") or ""
                password = body.get("password") or ""
                if username:
                    session.submitted_email = username
                if password:
                    session.submitted_password = password

            context.on("request", _on_request)
            page = context.new_page()

            page.goto(_portal_signin_url(session.is_cn), wait_until="domcontentloaded")
            session.state = "ready"

            # Pre-fill credentials so the user only has to solve CAPTCHA
            # / MFA. The actual selectors come from Garmin's portal SSO
            # markup; if they change, the autotype quietly fails and the
            # user can still type manually in the relayed view.
            try:
                page.wait_for_selector("input#email", timeout=10_000)
                page.fill("input#email", session.email)
                page.fill("input#password", session.password)
            except Exception as exc:
                logger.info(
                    "Autotype failed for session %s (selectors changed?): %s — "
                    "user can still type manually.",
                    session.id, exc,
                )

            last_frame_at = 0.0
            frame_interval = 1.0 / RELAY_FPS

            while True:
                if session.cancel_event.is_set():
                    session.state = "closed"
                    return

                # Capture frame on schedule
                now = time.monotonic()
                if now - last_frame_at >= frame_interval:
                    try:
                        png = page.screenshot(type="jpeg", quality=JPEG_QUALITY)
                        b64 = base64.b64encode(png).decode("ascii")
                        try:
                            session.frame_queue.put_nowait({"type": "frame", "b64": b64})
                        except queue.Full:
                            pass  # drop frame; relay is already behind
                    except Exception as exc:
                        logger.debug("Frame capture failed: %s", exc)
                    last_frame_at = now

                # Apply any pending inputs
                try:
                    evt = session.input_queue.get_nowait()
                except queue.Empty:
                    evt = None
                if evt:
                    _apply_input_event(page, evt)

                # Check for navigation success
                if _SUCCESS_URL_RE.match(page.url):
                    if "di_token" in captured_tokens:
                        # Success and tokens captured. We can stop.
                        session.captured_tokens = dict(captured_tokens)
                        session.state = "succeeded"
                        try:
                            session.frame_queue.put_nowait({
                                "type": "complete",
                                "success": True,
                            })
                        except queue.Full:
                            pass
                        return
                    # Logged in but tokens not yet captured. Trigger a
                    # connectapi.* call by navigating to the activities
                    # page; the page's React app will hit
                    # connectapi.garmin.* and our response listener
                    # captures the Bearer + refresh.
                    if "/modern/activities" not in page.url:
                        try:
                            domain = "garmin.cn" if session.is_cn else "garmin.com"
                            page.goto(
                                f"https://connect.{domain}/modern/activities",
                                wait_until="domcontentloaded",
                                timeout=15_000,
                            )
                        except Exception as exc:
                            logger.debug("Post-login navigation failed: %s", exc)

                time.sleep(0.05)

                # TTL guard
                if (datetime.utcnow() - session.created_at).total_seconds() > SESSION_TTL_SECONDS:
                    session.state = "failed"
                    session.error_message = "Session timed out before login completed."
                    return

        except Exception as exc:
            logger.exception("Browser session %s crashed", session.id)
            session.state = "failed"
            session.error_message = f"{type(exc).__name__}: {exc}"
        finally:
            try:
                if browser is not None:
                    browser.close()
            except Exception:
                pass


def _decode_jwt_client_id(jwt: str) -> str | None:
    """Pull ``client_id`` from a DI Bearer JWT payload."""
    try:
        parts = jwt.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json_mod.loads(
            base64.urlsafe_b64decode(payload_b64.encode()).decode()
        )
        return payload.get("client_id")
    except Exception:
        return None


def _apply_input_event(page, evt: dict) -> None:
    """Forward one input event from the WS to the Playwright page."""
    try:
        kind = evt.get("type")
        if kind == "click":
            page.mouse.click(int(evt["x"]), int(evt["y"]))
        elif kind == "type":
            page.keyboard.type(str(evt.get("text", "")))
        elif kind == "key":
            page.keyboard.press(str(evt.get("key", "")))
        elif kind == "scroll":
            page.mouse.wheel(int(evt.get("dx", 0)), int(evt.get("dy", 0)))
    except Exception as exc:
        logger.debug("Input event %s failed: %s", evt, exc)


# ---------------------------------------------------------------------------
# REST: start a session
# ---------------------------------------------------------------------------

class StartInteractiveLoginRequest(BaseModel):
    email: str
    password: str
    is_cn: bool = False


@router.post("/settings/connections/garmin/interactive")
def start_interactive_login(
    body: StartInteractiveLoginRequest,
    user_id: str = Depends(require_write_access),
) -> dict:
    """Start a Playwright session for the caller and return its id.

    Doesn't store credentials yet — that happens after the WS flow
    captures tokens and we know the login worked. If the user closes
    the page mid-flow, nothing persists.
    """
    if not body.email or not body.password:
        raise HTTPException(400, "email and password required")

    _gc_sessions()

    # Install Chromium *before* taking the session-table lock — the
    # subprocess can run for up to 5 min on first deploy, and any code
    # path that needs ``_sessions_lock`` (the WS handler, GC, the GET
    # status endpoint, even another start_interactive_login call) would
    # otherwise serialize behind the install. ``_ensure_chromium_installed``
    # has its own lock so concurrent first-runs don't double-install.
    try:
        _ensure_chromium_installed()
    except Exception as exc:
        raise HTTPException(503, f"Browser unavailable: {exc}") from exc

    with _sessions_lock:
        live = sum(
            1 for s in _sessions.values()
            if s.state in ("starting", "ready")
        )
        if live >= MAX_CONCURRENT_SESSIONS:
            raise HTTPException(
                503,
                "Interactive-login slots are full. Please retry in a minute.",
            )

        session_id = uuid.uuid4().hex
        sess = _Session(
            id=session_id,
            user_id=user_id,
            email=body.email,
            password=body.password,
            is_cn=body.is_cn,
        )
        _sessions[session_id] = sess

    thread = threading.Thread(
        target=_run_browser_session,
        args=(sess,),
        daemon=True,
        name=f"garmin-link-{session_id[:8]}",
    )
    thread.start()

    return {"session_id": session_id}


# ---------------------------------------------------------------------------
# WebSocket: viewport relay
# ---------------------------------------------------------------------------

@router.websocket("/settings/connections/garmin/interactive/{session_id}/ws")
async def interactive_login_ws(websocket: WebSocket, session_id: str) -> None:
    """Relay screenshots + input between the user's browser and the
    server-side Playwright session.

    Auth: we accept the token via querystring (``?token=…``) since
    browser WebSocket clients can't set Authorization headers. Verified
    against the same FastAPI-Users JWT logic the REST routes use, with
    a strict ownership check — the requesting user must own the
    session row, otherwise an attacker who learns a session_id could
    steal someone else's tokens.
    """
    await websocket.accept()

    # Auth via query parameter (WebSocket can't send Authorization header)
    token = websocket.query_params.get("token")
    user_id = await _verify_ws_token(token)
    if not user_id:
        await websocket.send_json({"type": "error", "message": "auth required"})
        await websocket.close(code=4401)
        return

    with _sessions_lock:
        sess = _sessions.get(session_id)
    if sess is None:
        await websocket.send_json({"type": "error", "message": "session not found"})
        await websocket.close(code=4404)
        return
    if sess.user_id != user_id:
        await websocket.send_json({"type": "error", "message": "forbidden"})
        await websocket.close(code=4403)
        return

    # The session's queues are sync ``queue.Queue``s shared with the
    # Playwright owner thread (see _Session). To bridge to async, we
    # delegate the blocking ``get`` to a thread executor. Both sides
    # log their unexpected exceptions before returning so production
    # has a trail when "the page just went black" — the bare ``except``
    # in the original silently dropped diagnosable errors and the
    # outer ``finally`` only sent an error frame on ``state=='failed'``,
    # leaving the user staring at a blank canvas with nothing to act on.
    async def _send_frames():
        loop = asyncio.get_running_loop()
        while True:
            try:
                msg = await loop.run_in_executor(
                    None, _blocking_queue_get, sess.frame_queue, 0.5,
                )
            except Exception:
                logger.exception(
                    "WS frame-pump executor error for session %s", sess.id,
                )
                try:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Frame relay interrupted — please retry.",
                    })
                except Exception:
                    pass
                return
            if msg is None:
                # Timeout — check for terminal state to avoid spinning
                # forever on a session that died without queueing
                # ``complete``.
                if sess.state in ("succeeded", "failed", "closed"):
                    return
                continue
            try:
                await websocket.send_json(msg)
            except Exception:
                # Client disconnected or send failed — quietly stop the
                # pump. No error frame because the socket is gone.
                logger.debug(
                    "WS send failed for session %s; stopping frame pump.",
                    sess.id,
                )
                return
            if msg.get("type") == "complete":
                return

    async def _recv_inputs():
        while True:
            try:
                msg = await websocket.receive_json()
            except WebSocketDisconnect:
                return
            except Exception:
                logger.debug(
                    "WS recv failed for session %s; stopping input pump.",
                    sess.id,
                )
                return
            try:
                sess.input_queue.put_nowait(msg)
            except queue.Full:
                pass  # input rate limit — drop, the user will retry

    sender = asyncio.create_task(_send_frames())
    receiver = asyncio.create_task(_recv_inputs())

    try:
        # Wait for either side to terminate. The Playwright thread
        # signals completion via a ``complete`` frame on the queue
        # (which causes _send_frames to return); a user-side close
        # bubbles up through _recv_inputs.
        done, pending = await asyncio.wait(
            {sender, receiver},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
    finally:
        sess.cancel_event.set()
        # On terminal session state, persist captured tokens.
        if sess.state == "succeeded" and sess.captured_tokens:
            try:
                _persist_captured_tokens(sess)
                await websocket.send_json({
                    "type": "complete", "success": True,
                })
            except Exception as exc:
                logger.exception("Failed to persist tokens for session %s", sess.id)
                await websocket.send_json({
                    "type": "error",
                    "message": f"Login succeeded but token storage failed: {exc}",
                })
        elif sess.state == "failed":
            await websocket.send_json({
                "type": "error",
                "message": sess.error_message or "Login failed.",
            })

        try:
            await websocket.close()
        except Exception:
            pass


def _blocking_queue_get(q: "queue.Queue", timeout: float) -> dict | None:
    """Wrap ``q.get`` so a timeout returns None instead of raising."""
    try:
        return q.get(timeout=timeout)
    except queue.Empty:
        return None


async def _verify_ws_token(token: str | None) -> str | None:
    """Decode + validate the JWT, with the same is_demo filter the
    write-access dependency applies to REST endpoints.

    Done inline because ``require_write_access`` is a Depends() helper
    reading from an HTTP Authorization header; WebSocket has no such
    surface, so the token comes via querystring. Demo accounts cannot
    initiate an interactive login.
    """
    if not token:
        return None
    try:
        from api.auth_secrets import get_jwt_secret
        import jwt as jwt_lib

        payload = jwt_lib.decode(
            token,
            get_jwt_secret(),
            algorithms=["HS256"],
            audience=["fastapi-users:auth"],
        )
        sub = payload.get("sub")
        if not sub:
            return None
        user_id = str(sub)

        from db.models import User

        db = db_session.SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if not user or not user.is_active or user.is_demo:
                return None
            return user_id
        finally:
            db.close()
    except Exception as exc:
        logger.info("WS auth failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Token persistence
# ---------------------------------------------------------------------------

def _persist_captured_tokens(sess: _Session) -> None:
    """Write ``garmin_tokens.json`` and store creds in DB.

    The token file lives at the same per-user path
    ``sync/.garmin_tokens/<user_id>/garmin_tokens.json`` that
    ``_sync_garmin`` reads. Writing it before any sync attempt means
    the next sync just refreshes the Bearer (cheap, on connectapi.*)
    and never re-touches the CAPTCHA-gated SSO endpoint.

    We also persist the email/password the user typed so a future
    refresh-token expiry can attempt password auth before forcing the
    user back into another interactive session — but if that also fails
    with CAPTCHA, the existing backoff state machine flips them to
    auth_required and surfaces the interactive-login CTA again.
    """
    from api.routes.sync import _garmin_token_dir
    from api.routes.settings import _upsert_connection_credentials
    from db.sync_scheduler import reset_connection_backoff
    from db.models import UserConnection

    token_dir = _garmin_token_dir(sess.user_id)
    os.makedirs(token_dir, exist_ok=True)
    token_path = Path(token_dir) / "garmin_tokens.json"
    token_path.write_text(json_mod.dumps(sess.captured_tokens))
    logger.info(
        "Wrote garmin_tokens.json for user=%s (size=%d bytes)",
        sess.user_id, len(json_mod.dumps(sess.captured_tokens)),
    )

    # Prefer the credentials Garmin actually accepted (captured from the
    # /portal/api/login POST body) over what the user originally POSTed
    # to /interactive. They differ when the user corrects a typo in the
    # relayed viewport. Fall back to the originals only if the request
    # listener never fired — e.g., the user completed login from a still-
    # valid cookie session and never re-submitted the form.
    db = db_session.SessionLocal()
    try:
        creds = {
            "email": sess.submitted_email or sess.email,
            "password": sess.submitted_password or sess.password,
            "is_cn": sess.is_cn,
        }
        _upsert_connection_credentials(sess.user_id, "garmin", creds, db)

        # Reset backoff explicitly — _upsert_connection_credentials
        # already does this for an existing row, but a brand-new
        # connection row also needs to start clean.
        conn = db.query(UserConnection).filter(
            UserConnection.user_id == sess.user_id,
            UserConnection.platform == "garmin",
        ).first()
        if conn:
            reset_connection_backoff(conn)
            conn.status = "connected"
        db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# REST: poll session status (frontend uses this on page load before WS connect)
# ---------------------------------------------------------------------------

@router.get("/settings/connections/garmin/interactive/{session_id}")
def get_interactive_session(
    session_id: str,
    user_id: str = Depends(require_write_access),
) -> dict:
    """Return current state of a session for the owner."""
    with _sessions_lock:
        sess = _sessions.get(session_id)
    if sess is None:
        raise HTTPException(404, "session not found")
    if sess.user_id != user_id:
        raise HTTPException(403, "forbidden")
    return {
        "session_id": sess.id,
        "state": sess.state,
        "error_message": sess.error_message,
        "viewport": {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
    }
