"""Regression tests for the Garmin per-user token directory.

A single shared `.garmin_tokens/` directory caused every user's sync to reuse
the first authenticated user's OAuth session and fetch that person's data
(garminconnect loads tokens from disk without validating whose account they
belong to). The fix scopes tokens per user_id and invalidates them when
credentials change.
"""
import os

import pytest

from api.routes.sync import (
    _garmin_token_dir,
    _garmin_token_root,
    clear_garmin_tokens,
)


def test_token_dir_is_unique_per_user() -> None:
    a = _garmin_token_dir("user-a")
    b = _garmin_token_dir("user-b")
    assert a != b
    assert a.startswith(_garmin_token_root())
    assert b.startswith(_garmin_token_root())


def test_token_dir_is_nested_directly_under_root_as_user_id() -> None:
    """Strong invariant: the path under the root is exactly the user_id.

    Rejects sharded variants like `root/first-char/full-id` that could collapse
    for IDs sharing a prefix.
    """
    uid = "abc-123"
    path = _garmin_token_dir(uid)
    assert os.path.relpath(path, _garmin_token_root()) == uid


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


def test_clear_garmin_tokens_is_noop_when_dir_missing(tmp_path, monkeypatch) -> None:
    """Clearing a non-existent directory must not raise — the connect-flow
    calls this unconditionally on first-ever Garmin connect."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    clear_garmin_tokens("never-synced-user")


def test_clear_garmin_tokens_propagates_filesystem_errors(tmp_path, monkeypatch) -> None:
    """Silencing rmtree failures would re-open the leak. Callers must see them."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))

    user_id = "user-err"
    os.makedirs(_garmin_token_dir(user_id), exist_ok=True)

    def _boom(*args, **kwargs):
        raise OSError("simulated permission denied")

    monkeypatch.setattr("shutil.rmtree", _boom)

    with pytest.raises(OSError):
        clear_garmin_tokens(user_id)


def test_sync_garmin_passes_per_user_path_to_login(tmp_path, monkeypatch) -> None:
    """The actual call site — not just the helper — must scope the token dir.

    A future refactor that inlined the path to a shared value would re-create
    the bug and every helper-level test would still pass. This test patches
    garminconnect.Garmin and asserts `login(token_dir)` receives a per-user
    path for two different user_ids.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))

    recorded: list[tuple[str, str]] = []

    class _FakeGarth:
        def dump(self, path: str) -> None:
            pass

    class _FakeGarminClient:
        def __init__(self, email: str, password: str, is_cn: bool = False):
            self.email = email
            self.garth = _FakeGarth()

        def login(self, token_dir: str) -> None:
            recorded.append((self.email, token_dir))

        def get_activities_by_date(self, start, end, activitytype=None):
            return []

        def get_activity_splits(self, aid):
            return {}

        def get_lactate_threshold(self, latest=False, start_date=None, end_date=None):
            return []

        def get_training_status(self, d):
            return {}

        def get_training_readiness(self, d):
            return None

        def get_race_predictions(self):
            return None

        def get_hrv_data(self, d):
            return None

        def get_sleep_data(self, d):
            return None

    monkeypatch.setattr("garminconnect.Garmin", _FakeGarminClient)

    # Stub DB-touching helpers so we don't need a full session
    monkeypatch.setattr("db.sync_writer.write_activities", lambda *a, **k: 0)
    monkeypatch.setattr("db.sync_writer.write_splits", lambda *a, **k: 0)
    monkeypatch.setattr("db.sync_writer.write_lactate_threshold", lambda *a, **k: 0)
    monkeypatch.setattr("db.sync_writer.write_daily_metrics", lambda *a, **k: 0)
    monkeypatch.setattr("db.sync_writer.write_recovery", lambda *a, **k: 0)

    class _FakeConfig:
        source_options = {"garmin_activity_categories": ["running"]}

    monkeypatch.setattr(
        "analysis.config.load_config_from_db", lambda user_id, db: _FakeConfig()
    )

    from api.routes.sync import _sync_garmin

    class _NullDB:
        def query(self, *a, **k):
            class _Q:
                def filter(self, *a, **k):
                    return self

                def first(self):
                    return None

            return _Q()

        def commit(self):
            pass

    creds_a = {"email": "a@example.com", "password": "pw"}
    creds_b = {"email": "b@example.com", "password": "pw"}
    _sync_garmin("user-a", creds_a, None, _NullDB())
    _sync_garmin("user-b", creds_b, None, _NullDB())

    assert len(recorded) == 2
    email_a, path_a = recorded[0]
    email_b, path_b = recorded[1]
    assert path_a != path_b
    assert path_a.endswith(os.sep + "user-a")
    assert path_b.endswith(os.sep + "user-b")
