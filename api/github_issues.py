"""Minimal GitHub Issues REST client for the feedback triage pipeline.

Why a hand-rolled client instead of PyGithub: we make exactly one call
(create an issue) against one repo, already depend on ``httpx``, and want to
avoid pulling a new dependency into ``requirements.txt`` for a single POST.

Configuration (all optional — when unset, issue creation is skipped and the
feedback row stays at ``triaged`` for manual admin promotion):

Auth uses a **GitHub App** (no token to rotate): ``PRAXYS_GITHUB_APP_ID`` +
``PRAXYS_GITHUB_APP_INSTALLATION_ID`` + ``PRAXYS_GITHUB_APP_PRIVATE_KEY`` (PEM).
We sign a short-lived JWT, exchange it for a ~1h installation token, and cache
it. The app needs *Issues: write* on the target repo. Setup:
``docs/ops/setup-github-app.md``.

- ``PRAXYS_FEEDBACK_GITHUB_REPO`` — ``owner/repo`` of the triage repo. Because
  the main repo is public, operators are encouraged to point this at a
  PRIVATE triage repo so even scrubbed reports aren't world-readable.
- ``PRAXYS_FEEDBACK_GITHUB_LABELS`` — comma-separated labels added to every
  issue *in addition* to the per-kind label (e.g. a label your coding-agent
  automation watches). Optional.
- ``PRAXYS_FEEDBACK_GITHUB_ASSIGNEES`` — comma-separated logins to assign
  (e.g. the GitHub Copilot coding-agent bot login, once enabled on the repo).
  Optional.

Nothing here raises to the caller: a GitHub outage must not turn into a
500 on the user's submit or an unhandled exception in a background task.
Failures return ``None`` (or are logged) so the triage step can mark the row
``failed`` and an admin can retry.
"""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger(__name__)

_API_ROOT = "https://api.github.com"
_API_VERSION = "2022-11-28"
_TIMEOUT_S = 15.0


def _repo() -> str | None:
    return os.environ.get("PRAXYS_FEEDBACK_GITHUB_REPO") or None


# --- GitHub App auth (preferred — no token to rotate) ----------------------

def _app_id() -> str | None:
    return os.environ.get("PRAXYS_GITHUB_APP_ID") or None


def _app_installation_id() -> str | None:
    return os.environ.get("PRAXYS_GITHUB_APP_INSTALLATION_ID") or None


def _app_private_key() -> str | None:
    raw = os.environ.get("PRAXYS_GITHUB_APP_PRIVATE_KEY") or None
    # App Service settings commonly hold the PEM single-line with literal "\n";
    # restore real newlines. A no-op on PEMs that already have newlines.
    return raw.replace("\\n", "\n") if raw else None


def _app_configured() -> bool:
    return bool(_app_id() and _app_installation_id() and _app_private_key())


# Cache the minted installation token until shortly before it expires (~1h
# lifetime) so we don't re-mint on every issue. Cleared by tests.
_install_token: dict = {"token": None, "exp": 0.0}


def _app_jwt() -> str | None:
    """Short-lived RS256 JWT authenticating AS the GitHub App."""
    try:
        import jwt  # PyJWT — already a dependency (see api/auth.py)
    except ImportError:  # pragma: no cover
        logger.warning("PyJWT missing — GitHub App auth unavailable")
        return None
    import time

    app_id, key = _app_id(), _app_private_key()
    if not app_id or not key:
        return None
    now = int(time.time())
    # iat backdated 60s for clock skew; exp must be <= 10 min per GitHub.
    payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": app_id}
    try:
        return jwt.encode(payload, key, algorithm="RS256")
    except Exception:
        logger.warning("GitHub App JWT signing failed — check the private key", exc_info=True)
        return None


def _mint_installation_token() -> str | None:
    """Exchange the app JWT for a ~1h installation access token, and cache it."""
    import time
    from datetime import datetime

    app_jwt = _app_jwt()
    installation_id = _app_installation_id()
    if not app_jwt or not installation_id:
        return None
    url = f"{_API_ROOT}/app/installations/{installation_id}/access_tokens"
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": _API_VERSION,
        "User-Agent": "praxys-feedback",
    }
    try:
        resp = httpx.post(url, headers=headers, timeout=_TIMEOUT_S)
    except httpx.HTTPError as exc:
        logger.warning("GitHub App token mint failed (network): %s", exc)
        return None
    if resp.status_code != 201:
        logger.warning(
            "GitHub App token mint failed: HTTP %s (%s)",
            resp.status_code, resp.reason_phrase,
        )
        return None
    # Parse once; a malformed-but-201 body must degrade to None (the module
    # contract is "never raise to the caller" — the admin approve route calls
    # create_issue without its own guard around the mint).
    try:
        data = resp.json() or {}
    except Exception:
        logger.warning("GitHub App token mint returned a non-JSON 201 body")
        return None
    token = data.get("token")
    if not token:
        return None
    # Refresh 5 min before the stated expiry; fall back to ~50 min.
    exp_epoch = time.time() + 3000
    try:
        exp_str = data.get("expires_at")
        if exp_str:
            exp_epoch = datetime.fromisoformat(exp_str.replace("Z", "+00:00")).timestamp() - 300
    except Exception:
        pass
    _install_token["token"] = token
    _install_token["exp"] = exp_epoch
    return token


def _bearer_token() -> str | None:
    """Return a cached/auto-minted GitHub App installation token, or ``None``.

    No rotation: the token lives ~1h and is re-minted on demand just before it
    expires. ``None`` when the GitHub App isn't configured.
    """
    if not _app_configured():
        return None
    import time

    cached = _install_token["token"]
    if cached and _install_token["exp"] > time.time():
        return cached
    return _mint_installation_token()


def is_configured() -> bool:
    """True iff a target repo and the GitHub App credentials are set."""
    return bool(_repo() and _app_configured())


def _csv_env(name: str) -> list[str]:
    """Parse a comma-separated env var into a trimmed, non-empty list."""
    raw = os.environ.get(name, "") or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


def extra_labels() -> list[str]:
    """Operator-configured labels added to every feedback issue."""
    return _csv_env("PRAXYS_FEEDBACK_GITHUB_LABELS")


def assignees() -> list[str]:
    """Operator-configured assignees (e.g. the coding-agent bot login)."""
    return _csv_env("PRAXYS_FEEDBACK_GITHUB_ASSIGNEES")


def create_issue(
    *,
    title: str,
    body: str,
    labels: list[str] | None = None,
    assignees_override: list[str] | None = None,
) -> dict | None:
    """Create a GitHub issue and return ``{"number", "url"}`` or ``None``.

    ``None`` is returned (and the cause logged) when GitHub isn't configured or
    the API call fails for any reason. Callers must treat ``None`` as
    "not published" and persist a retryable state.
    """
    token, repo = _bearer_token(), _repo()
    if not token or not repo:
        logger.info("GitHub issue creation skipped — GitHub App not configured "
                    "or PRAXYS_FEEDBACK_GITHUB_REPO unset")
        return None

    payload: dict = {"title": title[:256], "body": body}
    all_labels = list(labels or []) + extra_labels()
    if all_labels:
        # De-dupe while preserving order.
        payload["labels"] = list(dict.fromkeys(all_labels))
    who = assignees_override if assignees_override is not None else assignees()
    if who:
        payload["assignees"] = who

    url = f"{_API_ROOT}/repos/{repo}/issues"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": _API_VERSION,
        "User-Agent": "praxys-feedback",
    }
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=_TIMEOUT_S)
    except httpx.HTTPError as exc:
        logger.warning("GitHub issue creation failed (network): %s", exc)
        return None

    if resp.status_code not in (200, 201):
        # Don't log the response body verbatim at INFO — it can echo the
        # submitted title. Status + a short reason is enough for operators.
        logger.warning(
            "GitHub issue creation failed: HTTP %s (%s)",
            resp.status_code, resp.reason_phrase,
        )
        return None

    data = resp.json()
    return {"number": data.get("number"), "url": data.get("html_url")}
