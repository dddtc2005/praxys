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

    # Pre-create token files so _sync_garmin passes the path to login().
    # The bug fix makes login receive None on first-time sync (no tokens),
    # but the isolation guarantee still matters once tokens exist — so we
    # exercise the cached-tokens branch here.
    for uid in ("user-a", "user-b"):
        d = _garmin_token_dir(uid)
        os.makedirs(d, exist_ok=True)
        for name in ("oauth1_token.json", "oauth2_token.json"):
            with open(os.path.join(d, name), "w") as f:
                f.write("{}")

    recorded_login: list[tuple[str, str]] = []
    recorded_dump: list[tuple[str, str]] = []

    class _FakeGarth:
        def __init__(self, email: str) -> None:
            self._email = email

        def dump(self, path: str) -> None:
            recorded_dump.append((self._email, path))

    class _FakeGarminClient:
        def __init__(self, email: str, password: str, is_cn: bool = False):
            self.email = email
            self.garth = _FakeGarth(email)

        def login(self, token_dir) -> None:
            recorded_login.append((self.email, token_dir))

        def get_activities_by_date(self, start, end, activitytype=None):
            return []

        def get_activity_splits(self, aid):
            return {}

        def get_lactate_threshold(self, latest=False, start_date=None, end_date=None):
            return []

        def get_user_profile(self):
            return {}

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
    monkeypatch.setattr("db.sync_writer.write_profile_thresholds", lambda *a, **k: 0)

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

    assert len(recorded_login) == 2
    email_a, path_a = recorded_login[0]
    email_b, path_b = recorded_login[1]
    assert path_a != path_b
    assert path_a.endswith(os.sep + "user-a")
    assert path_b.endswith(os.sep + "user-b")

    # Dump should also go to each user's own directory so next sync can reuse.
    assert len(recorded_dump) == 2
    dump_a = dict(recorded_dump)["a@example.com"]
    dump_b = dict(recorded_dump)["b@example.com"]
    assert dump_a.endswith(os.sep + "user-a")
    assert dump_b.endswith(os.sep + "user-b")


def test_sync_garmin_first_time_login_without_tokens(tmp_path, monkeypatch) -> None:
    """Regression: first-ever sync must not pass a tokenstore path to login().

    garminconnect.login() delegates to garth.load(), which raises
    FileNotFoundError when oauth1_token.json / oauth2_token.json aren't in
    the directory. Our code used to pass the path unconditionally, so the
    first sync for any new user crashed before fetching any data. Fix: pass
    None when no token files exist; dump after the credential-based login
    so the next sync can use the cached tokens.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))

    login_args: list[object] = []
    dump_paths: list[str] = []

    class _FakeGarth:
        def dump(self, path: str) -> None:
            dump_paths.append(path)

    class _FakeGarminClient:
        def __init__(self, email: str, password: str, is_cn: bool = False):
            self.garth = _FakeGarth()

        def login(self, token_dir) -> None:
            login_args.append(token_dir)

        def get_activities_by_date(self, *a, **k):
            return []

        def get_activity_splits(self, aid):
            return {}

        def get_lactate_threshold(self, **kwargs):
            return []

        def get_user_profile(self):
            return {}

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
    for name in (
        "write_activities", "write_splits", "write_lactate_threshold",
        "write_daily_metrics", "write_recovery", "write_profile_thresholds",
    ):
        monkeypatch.setattr(f"db.sync_writer.{name}", lambda *a, **k: 0)

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

    _sync_garmin(
        "first-time-user", {"email": "x@example.com", "password": "pw"},
        None, _NullDB(),
    )

    assert login_args == [None], (
        "login() must receive None when the tokenstore has no token files; "
        f"got {login_args!r}"
    )
    assert len(dump_paths) == 1
    assert dump_paths[0].endswith(os.sep + "first-time-user"), (
        "dump() must still scope the saved tokens per-user"
    )


def test_sync_garmin_recovery_loop_survives_a_malformed_day(tmp_path, monkeypatch) -> None:
    """Regression: one corrupt Garmin payload must not skip remaining days.

    Before the per-day try/except was added in _sync_garmin's recovery loop,
    an AttributeError inside parse_garmin_recovery (e.g. from Garmin
    returning a present-but-null nested key that .get() couldn't default
    away) propagated to the outer try/except and aborted the whole window,
    writing zero recovery rows. This test simulates that: day 0 returns a
    payload that makes parse_garmin_recovery raise; day 1 returns a valid
    payload; write_recovery must still receive the day-1 row.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))

    # Pre-create tokens so login is skipped via cached path
    token_root = _garmin_token_dir("bad-day-user")
    os.makedirs(token_root, exist_ok=True)
    for name in ("oauth1_token.json", "oauth2_token.json"):
        with open(os.path.join(token_root, name), "w") as f:
            f.write("{}")

    day_calls: dict[str, list[str]] = {"hrv": [], "sleep": []}
    recovery_write_calls: list[list[dict]] = []

    class _FakeGarth:
        def dump(self, path): pass

    class _FakeClient:
        def __init__(self, email, password, is_cn=False):
            self.garth = _FakeGarth()

        def login(self, token_dir): pass
        def get_activities_by_date(self, *a, **k): return []
        def get_activity_splits(self, aid): return {}
        def get_lactate_threshold(self, **kwargs): return []
        def get_user_profile(self): return {}
        def get_training_status(self, d): return {}
        def get_training_readiness(self, d): return None
        def get_race_predictions(self): return None

        def get_hrv_data(self, d):
            day_calls["hrv"].append(d)
            # First iteration (today) → malformed. Later iterations → valid.
            if len(day_calls["hrv"]) == 1:
                # Make float() blow up inside parse_garmin_recovery
                return {"hrvSummary": {"lastNightAvg": "not-a-number"}}
            return {"hrvSummary": {"lastNightAvg": 42}}

        def get_sleep_data(self, d):
            day_calls["sleep"].append(d)
            return {"dailySleepDTO": {"sleepScore": 80, "restingHeartRate": 50}}

    monkeypatch.setattr("garminconnect.Garmin", _FakeClient)
    monkeypatch.setattr("db.sync_writer.write_activities", lambda *a, **k: 0)
    monkeypatch.setattr("db.sync_writer.write_splits", lambda *a, **k: 0)
    monkeypatch.setattr("db.sync_writer.write_lactate_threshold", lambda *a, **k: 0)
    monkeypatch.setattr("db.sync_writer.write_daily_metrics", lambda *a, **k: 0)
    monkeypatch.setattr("db.sync_writer.write_profile_thresholds", lambda *a, **k: 0)

    def _fake_write_recovery(user_id, readiness, sleep, hrv, db, *, garmin_recovery=None):
        recovery_write_calls.append(list(garmin_recovery or []))
        return len(garmin_recovery or [])

    monkeypatch.setattr("db.sync_writer.write_recovery", _fake_write_recovery)

    class _FakeConfig:
        source_options = {"garmin_activity_categories": ["running"]}

    monkeypatch.setattr(
        "analysis.config.load_config_from_db", lambda user_id, db: _FakeConfig()
    )

    from api.routes.sync import _sync_garmin

    class _NullDB:
        def query(self, *a, **k):
            class _Q:
                def filter(self, *a, **k): return self
                def first(self): return None
            return _Q()
        def commit(self): pass

    result = _sync_garmin(
        "bad-day-user",
        {"email": "x@example.com", "password": "pw"},
        None, _NullDB(),
    )

    # Default window is today..today-7 inclusive (8 days). Day 0 is corrupt,
    # remaining 7 produce rows — the loop must not abort on the first failure.
    expected_days = len(day_calls["hrv"])
    assert expected_days >= 7, f"Loop aborted early: {day_calls}"
    assert len(recovery_write_calls) == 1, (
        "write_recovery should be called exactly once with the surviving rows"
    )
    good_rows = recovery_write_calls[0]
    assert len(good_rows) == expected_days - 1, (
        f"Expected {expected_days - 1} good rows (day 0 skipped), "
        f"got {len(good_rows)}"
    )
    assert result.get("recovery") == len(good_rows)
