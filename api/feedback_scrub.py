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

import json
import re

from api.version import find_valid_build_versions, is_valid_build_version

# RFC 5322 is famously unparseable in full; this pragmatic pattern matches the
# overwhelming majority of real addresses without catastrophic backtracking.
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# IPv4 dotted-quad. We don't redact IPv6 by default (rare in free-text
# feedback and prone to false positives against hex IDs).
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

# "Authorization: Bearer <token>" / "token=..." style secrets.
_AUTHORIZATION_HEADER_RE = re.compile(
    r"(?im)(?<![\"'])\b(authorization)\b(?![\"'])\s*[:=]\s*[^;\r\n]+"
)
_COOKIE_HEADER_RE = re.compile(r"(?im)\b(set-cookie|cookie)\s*:\s*[^\r\n]+")
_URI_CREDENTIAL_RE = re.compile(
    r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^@\s/]+@"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?im)\b("
    r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_(?:KEY|TOKEN|SECRET|PASSWORD|PWD)"
    r"|(?:[A-Z][A-Z0-9]*_)*(?:DATABASE_URL|DATABASE_URI|CONNECTION_STRING)"
    r"|AccountKey|SharedAccessKey|SharedAccessSignature|client_secret|api_key"
    r"|access_token|refresh_token|database_url|database_uri|connection_string"
    r")\s*[:=]\s*"
    r"(?:\"[^\"\r\n]{1,500}\"|'[^'\r\n]{1,500}'|[^;\s\r\n]+)"
)
_JSON_CREDENTIAL_RE = re.compile(
    r"(?ix)"
    r"(?P<prefix>[\"'](?:authorization|bearer|access[\s_-]?token|"
    r"refresh[\s_-]?token|client[\s_-]?secret|token|api[\s_-]?key|"
    r"secret|password|pwd|cookie|set-cookie|database_url|database_uri|"
    r"connection_string|accountkey|sharedaccesskey|sharedaccesssignature)"
    r"[\"']\s*:\s*)"
    r"(?:\"(?:\\.|[^\"\\\r\n])*\"|'(?:\\.|[^'\\\r\n])*'|"
    r"\[[^\]\r\n]*\]|\{[^}\r\n]*\}|[^,}\r\n]+)"
)
_SENSITIVE_JSON_KEYS = frozenset({
    "authorization", "bearer", "token", "tokens", "accesstoken",
    "refreshtoken", "idtoken", "clientsecret", "oauthtoken", "apikey",
    "secret", "secrets", "password", "passwords", "passwd", "pwd",
    "cookie", "cookies", "setcookie", "databaseurl", "databaseuri",
    "connectionstring", "accountkey", "sharedaccesskey",
    "sharedaccesssignature", "privatekey", "credential", "credentials",
})
_SENSITIVE_JSON_KEY_SUFFIXES = (
    "apikey", "accesstoken", "refreshtoken", "idtoken", "oauthtoken",
    "token", "tokens", "clientsecret", "secret", "secrets", "password",
    "passwords", "passwd", "pwd", "accesskey", "privatekey",
    "connectionstring", "credential", "credentials", "authorization",
    "cookie", "cookies", "setcookie",
)
_PEM_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
    r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)

_BEARER_RE = re.compile(
    r"(?ix)"
    r"(?<![\"'])\b(authorization|bearer|access[\s_-]?token|refresh[\s_-]?token|"
    r"client[\s_-]?secret|token|api[\s_-]?key|secret|password|pwd)\b(?![\"'])"
    r"\s*(?:(?:is|was)\s*)?[:=]?\s*"
    r"(?:bearer\s+\S+|\"[^\"\r\n]{1,200}\"|'[^'\r\n]{1,200}'|\S+)"
)

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

# Formatted phone/card/account candidates. The callback below counts digits so
# dates such as 2026-07-12 (eight digits) survive while common separators do not
# bypass the long-number privacy boundary.
_FORMATTED_NUMBER_RE = re.compile(r"(?<!\d)\+?[\d(][\d\s().-]{7,}\d(?!\d)")

# Long contiguous digit runs (>=9). Short runs are left alone so training
# numbers (power 250, HR 165) survive.
_LONG_DIGITS_RE = re.compile(r"\b\d{9,}\b")


def _redact_formatted_number(match: re.Match[str]) -> str:
    value = match.group(0)
    digit_count = sum(char.isdigit() for char in value)
    return "[redacted-number]" if digit_count >= 9 else value


def _protect_build_versions(text: str) -> tuple[str, dict[str, str]]:
    """Protect strict public build IDs from generic long-number redaction."""
    protected = text
    placeholders: dict[str, str] = {}
    placeholder_index = 0
    for version in find_valid_build_versions(text):
        while True:
            placeholder = f"__praxys_build_{placeholder_index}__"
            placeholder_index += 1
            if placeholder not in protected:
                break
        protected = protected.replace(version, placeholder)
        placeholders[placeholder] = version
    return protected, placeholders


def _scrub_unstructured_text(text: str) -> str:
    """Scrub a plain-text fragment without attempting JSON parsing."""
    out, protected_build_versions = _protect_build_versions(text)
    out = _PEM_PRIVATE_KEY_RE.sub("[redacted-private-key]", out)
    out = _JSON_CREDENTIAL_RE.sub(r'\g<prefix>"[redacted]"', out)
    out = _AUTHORIZATION_HEADER_RE.sub(r"\1 [redacted]", out)
    out = _COOKIE_HEADER_RE.sub(r"\1: [redacted]", out)
    out = _SECRET_ASSIGNMENT_RE.sub(r"\1=[redacted]", out)
    out = _URI_CREDENTIAL_RE.sub(r"\1[redacted]@", out)
    out = _JWT_RE.sub("[redacted-token]", out)
    out = _KEYISH_RE.sub("[redacted-key]", out)
    out = _BEARER_RE.sub(r"\1 [redacted]", out)
    out = _EMAIL_RE.sub("[redacted-email]", out)
    out = _WIN_USER_RE.sub(r"\1[user]", out)
    out = _NIX_HOME_RE.sub(r"\1[user]", out)
    out = _IPV4_RE.sub("[redacted-ip]", out)
    out = _FORMATTED_NUMBER_RE.sub(_redact_formatted_number, out)
    out = _LONG_DIGITS_RE.sub("[redacted-number]", out)
    for placeholder, version in protected_build_versions.items():
        out = out.replace(placeholder, version)
    return out


def _is_sensitive_json_key(key: str) -> bool:
    """Return whether a normalized JSON key labels credential material."""
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
    return (
        normalized in _SENSITIVE_JSON_KEYS
        or normalized.endswith(_SENSITIVE_JSON_KEY_SUFFIXES)
    )


def _scrub_json_value(value: object) -> object:
    """Recursively scrub a value from a parsed JSON document."""
    if isinstance(value, dict):
        sensitive_value_field = any(
            re.sub(r"[^a-z0-9]", "", str(label_key).casefold())
            in {"name", "key", "header"}
            and isinstance(label_value, str)
            and _is_sensitive_json_key(label_value)
            for label_key, label_value in value.items()
        )
        cleaned: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            cleaned_key = _scrub_unstructured_text(key_text)
            redact_value = (
                sensitive_value_field
                and re.sub(r"[^a-z0-9]", "", key_text.casefold())
                in {"value", "values"}
            )
            cleaned[cleaned_key] = (
                "[redacted]"
                if redact_value or _is_sensitive_json_key(key_text)
                else _scrub_json_value(item)
            )
        return cleaned
    if isinstance(value, list):
        return [_scrub_json_value(item) for item in value]
    if isinstance(value, str):
        return _scrub_unstructured_text(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        raw = str(value)
        scrubbed = _scrub_unstructured_text(raw)
        return scrubbed if scrubbed != raw else value
    return value


def _scrub_json_document(text: str) -> str | None:
    """Return scrubbed JSON when ``text`` is a complete object or array."""
    stripped = text.strip()
    if not stripped or stripped[0] not in "[{":
        return None
    try:
        value = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(value, (dict, list)):
        return None
    return json.dumps(
        _scrub_json_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def scrub_text(text: str | None) -> str:
    """Return ``text`` with emails, secrets, IPs, home paths, and long digit
    runs replaced by stable placeholders.

    Complete JSON documents are parsed so sensitive object or array values are
    removed atomically without corrupting the remaining structure. For ordinary
    text, order matters: JWT / key-ish / bearer patterns run before the generic
    email + digit passes so a token containing an ``@`` or a long digit run is
    redacted as one value.
    """
    if not text:
        return ""
    scrubbed_json = _scrub_json_document(text)
    if scrubbed_json is not None:
        return scrubbed_json
    return _scrub_unstructured_text(text)


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
            normalized = val.strip()
            if (
                key in {"app_version", "api_version"}
                and is_valid_build_version(normalized)
            ):
                cleaned[key] = normalized
            else:
                cleaned[key] = scrub_text(val)[:500]
        elif isinstance(val, (int, float, bool)):
            cleaned[key] = val
    return cleaned
