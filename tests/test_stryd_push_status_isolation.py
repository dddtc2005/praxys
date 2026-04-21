"""Stryd push-status must be isolated per user.

A single shared `stryd_push_status.json` used to leak one user's workout IDs
and push timestamps to every other caller of ``GET /api/plan/stryd-status``.
Scoping by user_id at the storage layer is the fix; these tests lock the
invariant down behaviorally.
"""
import os

import pytest


@pytest.fixture(autouse=True)
def _tmpdir_data(tmp_path, monkeypatch):
    """Redirect the module's _DATA_DIR into a scratch directory per test."""
    from api.routes import plan as plan_mod

    scratch = tmp_path / "data"
    scratch.mkdir()
    monkeypatch.setattr(plan_mod, "_DATA_DIR", str(scratch))
    monkeypatch.setattr(
        plan_mod, "_STRYD_PUSH_STATUS_DIR",
        os.path.join(str(scratch), "ai", "stryd_push_status"),
    )
    yield


def test_path_is_unique_per_user():
    from api.routes.plan import _stryd_push_status_path

    a = _stryd_push_status_path("user-a")
    b = _stryd_push_status_path("user-b")
    assert a != b
    assert a.endswith("user-a.json")
    assert b.endswith("user-b.json")


def test_save_and_load_roundtrip_per_user():
    from api.routes.plan import _load_push_status, _save_push_status

    _save_push_status("alice", {"2026-05-01": {"workout_id": "alice-w1"}})
    assert _load_push_status("alice") == {"2026-05-01": {"workout_id": "alice-w1"}}


def test_one_users_save_is_invisible_to_another():
    """The core regression: one user's writes must NOT leak via another's read."""
    from api.routes.plan import _load_push_status, _save_push_status

    _save_push_status("alice", {"2026-05-01": {"workout_id": "alice-w1"}})
    assert _load_push_status("bob") == {}, "Bob must not see Alice's push history"


def test_missing_user_returns_empty_dict():
    """Never-pushed users must see an empty status without raising."""
    from api.routes.plan import _load_push_status

    assert _load_push_status("never-pushed") == {}


def test_corrupt_file_falls_back_to_empty(tmp_path):
    """A hand-edited or partially written file must not 500 the endpoint."""
    from api.routes import plan as plan_mod
    from api.routes.plan import _load_push_status

    path = plan_mod._stryd_push_status_path("corrupt-user")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("{this is not json")

    assert _load_push_status("corrupt-user") == {}
