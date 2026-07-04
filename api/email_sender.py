"""Optional, security-hardened SMTP email sender.

Praxys has no email infrastructure of its own; this is the single send path,
used by (1) email-ownership verification for open self-registration and (2)
emailing invitation codes to waitlist signups. It is intentionally built like
the other optional integrations (api/github_issues.py): when unconfigured,
:func:`is_available` returns False and callers fall back to a copy/mailto flow
— the app works fully without it.

Provider: designed for WeCom / Tencent Exmail (smtp.exmail.qq.com:465, SSL)
using a client authorization code, but works with any authenticated SMTP relay.
Kept behind this thin interface so an HTTPS provider (e.g. Azure Communication
Services) can be dropped in later without touching call sites.

Security design:
  * Credentials come only from env / App Service settings — never hard-coded,
    never logged, never returned by any API.
  * TLS is mandatory: implicit TLS via SMTP_SSL on 465 (default), or STARTTLS
    on 587. Both use ``ssl.create_default_context()`` which verifies the
    server certificate AND hostname. There is no plaintext fallback.
  * Header-injection safe: headers are set through ``EmailMessage`` and every
    caller-supplied header value is rejected if it contains CR/LF.
  * Not an open relay: callers pass a single recipient that the caller has
    already constrained to a trusted source (a waitlist row / the registering
    user's own address). This module additionally validates the address shape.
  * Fail-closed but never fatal: any error returns False (logged without the
    body or credentials); it never raises to the caller, so an SMTP outage
    can't 500 a request or crash a background task.
"""
from __future__ import annotations

import logging
import os
import re
import smtplib
import ssl
from email.message import EmailMessage

logger = logging.getLogger(__name__)

_TIMEOUT_S = 20.0
# Deliberately conservative address check. Real validation happens upstream
# (pydantic EmailStr on the waitlist/register payloads); this is a defensive
# backstop that also guarantees no CR/LF can reach a header.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _get(name: str) -> str | None:
    val = os.environ.get(name)
    return val.strip() if val else None


def _host() -> str | None:
    return _get("PRAXYS_SMTP_HOST")


def _port() -> int:
    try:
        return int(_get("PRAXYS_SMTP_PORT") or "465")
    except ValueError:
        return 465


def _user() -> str | None:
    return _get("PRAXYS_SMTP_USER")


def _password() -> str | None:
    # Not stripped-logged anywhere. Read on demand only.
    raw = os.environ.get("PRAXYS_SMTP_PASSWORD")
    return raw or None


def _from_addr() -> str | None:
    # Full From header (may include a display name, e.g. "Praxys <no-reply@praxys.run>").
    # Falls back to the auth user, which is the common case for Exmail.
    return _get("PRAXYS_SMTP_FROM") or _user()


def _use_starttls() -> bool:
    return (_get("PRAXYS_SMTP_STARTTLS") or "false").lower() in {"1", "true", "yes", "on"}


def is_available() -> bool:
    """True iff enough SMTP settings are present to attempt a send."""
    return bool(_host() and _user() and _password() and _from_addr())


def _valid_header_value(value: str) -> bool:
    """Reject values that could inject additional headers."""
    return "\r" not in value and "\n" not in value


def send_email(
    to: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
) -> bool:
    """Send one email. Returns True on success, False otherwise (never raises).

    ``to`` must be a single, well-formed address. ``subject`` must be free of
    CR/LF. On any failure the reason is logged *without* the body or any
    credential, and False is returned so the caller can fall back gracefully.
    """
    if not is_available():
        logger.info("email_sender: not configured; skipping send")
        return False

    to = (to or "").strip()
    if not _EMAIL_RE.match(to):
        logger.warning("email_sender: refusing to send to malformed address")
        return False
    if not _valid_header_value(subject):
        logger.warning("email_sender: refusing subject with CR/LF")
        return False

    from_addr = _from_addr()
    if not from_addr or not _valid_header_value(from_addr):
        logger.warning("email_sender: invalid From configured")
        return False

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    host = _host()
    port = _port()
    context = ssl.create_default_context()

    try:
        if _use_starttls():
            with smtplib.SMTP(host, port, timeout=_TIMEOUT_S) as server:
                server.starttls(context=context)
                server.login(_user(), _password())
                server.send_message(msg)
        else:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=_TIMEOUT_S) as server:
                server.login(_user(), _password())
                server.send_message(msg)
        # Log success without the recipient (PII) or any content.
        logger.info("email_sender: message sent (subject=%r)", subject)
        return True
    except Exception as exc:  # noqa: BLE001 — deliberately broad; must never propagate
        # Log the exception CLASS only — never str(exc), which for smtplib auth
        # errors can echo parts of the exchange. Never the body or credentials.
        logger.warning("email_sender: send failed (%s)", type(exc).__name__)
        return False