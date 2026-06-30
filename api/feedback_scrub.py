"""Deterministic PII / secret scrubbing for user-submitted feedback.

This repo is public, so anything that may end up in a GitHub issue must be
sanitized first. The LLM triage step (:mod:`api.feedback_triage`) rewrites
feedback into a clean title/body, but we do *not* trust the model to be a
reliable redactor — so every string published externally also passes through
the regex scrub here as a deterministic backstop. When the LLM is unavailable,
this scrub is the *only* sanitizer, so it is intentionally conservative.

All functions are pure (no I/O, no global state) and unit-tested in
``tests/test_feedback.py``. Patterns are deliberately broad: a false-positive
redaction (over-scrubbing) is acceptable; leaking a real secret is not.
"""
from __future__ import annotations

import re

# RFC 5322 is famously unparseable in full; this pragmatic pattern matches the
# overwhelming majority of real addresses without catastrophic backtracking.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# IPv4 dotted-quad. We don't redact IPv6 by default (rare in free-text
# feedback and prone to false positives against hex IDs).
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# "Authorization: Bearer <token>" / "token=..." style secrets.
_BEARER_RE = re.compile(r"(?i)\b(bearer|token|apikey|api[_-]?key|secret|password|pwd)\b\s*[:=]?\s*\S+")

# JWTs: three base64url segments separated by dots.
_JWT_RE = re.compile(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+\b")

# Common provider key prefixes (OpenAI sk-/sk-proj-/sk-svcacct-, GitHub
# ghp_/gho_/ghs_/github_pat_, AWS AKIA, Slack xox...). Kept as an alternation
# of well-known shapes rather than "any long token" to limit false positives.
# The OpenAI and fine-grained-PAT alternatives allow '-'/'_' in the body so
# modern hyphenated keys (sk-proj-..., github_pat_...) are matched whole.
_KEYISH_RE = re.compile(
    r"\b("
    r"sk-[A-Za-z0-9_-]{20,}"
    r"|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|AKIA[0-9A-Z]{12,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}"
    r")\b"
)

# Windows + Unix home directories embed the OS username in stack traces and
# pasted paths (C:\Users\jane\..., /home/jane/..., /Users/jane/...).
_WIN_USER_RE = re.compile(r"(?i)([A-Z]:\\Users\\)[^\\/\s]+")
_NIX_HOME_RE = re.compile(r"(/(?:home|Users)/)[^/\s]+")

# Long digit runs (>=9) — phone numbers, national IDs, account numbers. Short
# runs are left alone so training numbers (power 250, HR 165, dates) survive.
_LONG_DIGITS_RE = re.compile(r"\b\d{9,}\b")


def scrub_text(text: str | None) -> str:
    """Return ``text`` with emails, secrets, IPs, home paths, and long digit
    runs replaced by stable placeholders.

    Order matters: JWT / key-ish / bearer patterns run before the generic
    email + digit passes so a token that happens to contain an ``@`` or a long
    digit run is redacted as a whole token first.
    """
    if not text:
        return ""
    out = _JWT_RE.sub("[redacted-token]", text)
    out = _KEYISH_RE.sub("[redacted-key]", out)
    out = _BEARER_RE.sub(r"\1 [redacted]", out)
    out = _EMAIL_RE.sub("[redacted-email]", out)
    out = _WIN_USER_RE.sub(r"\1[user]", out)
    out = _NIX_HOME_RE.sub(r"\1[user]", out)
    out = _IPV4_RE.sub("[redacted-ip]", out)
    out = _LONG_DIGITS_RE.sub("[redacted-number]", out)
    return out


def scrub_context(context: dict | None) -> dict:
    """Scrub a client-supplied diagnostic-context dict.

    Only a known-safe allowlist of keys is retained, and every retained string
    value is run through :func:`scrub_text`. Unknown keys are dropped rather
    than published — a client (or a tampered request) can't smuggle arbitrary
    fields into a public issue.
    """
    if not context:
        return {}
    allowed = ("page", "app_version", "api_version", "platform", "user_agent", "viewport", "locale")
    cleaned: dict = {}
    for key in allowed:
        val = context.get(key)
        if val is None:
            continue
        if isinstance(val, str):
            cleaned[key] = scrub_text(val)[:500]
        elif isinstance(val, (int, float, bool)):
            cleaned[key] = val
    return cleaned
