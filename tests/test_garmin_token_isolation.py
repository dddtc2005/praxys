"""Regression tests for the Garmin per-user token directory.

Issue #56: a single shared `.garmin_tokens/` directory caused every user's
sync to reuse the first authenticated user's OAuth session and fetch that
person's data. The fix scopes tokens per user_id and invalidates them when
credentials change.
"""
import os

from api.routes.sync import (
    _garmin_token_dir,
    _garmin_token_root,
    clear_garmin_tokens,
)


def test_token_dir_is_unique_per_user() -> None:
    """Two users must not share a tokenstore path."""
    a = _garmin_token_dir("user-a")
    b = _garmin_token_dir("user-b")
    assert a != b
    assert a.startswith(_garmin_token_root())
    assert b.startswith(_garmin_token_root())


def test_token_dir_is_nested_under_user_id() -> None:
    """The per-user directory name must be the user_id itself — no shared prefix."""
    path = _garmin_token_dir("abc-123")
    assert os.path.basename(path) == "abc-123"


def test_clear_garmin_tokens_removes_directory(tmp_path, monkeypatch) -> None:
    """Invalidation must delete the tokenstore so the next login re-auths."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))

    user_id = "user-x"
    path = _garmin_token_dir(user_id)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "oauth1_token.json"), "w") as f:
        f.write("{}")
    assert os.path.isdir(path)

    clear_garmin_tokens(user_id)
    assert not os.path.isdir(path)


def test_clear_garmin_tokens_is_idempotent(tmp_path, monkeypatch) -> None:
    """Clearing a non-existent directory must not raise."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    clear_garmin_tokens("never-synced-user")
