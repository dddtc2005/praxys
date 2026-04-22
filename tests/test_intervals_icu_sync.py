from unittest.mock import MagicMock, patch

import pytest

from sync.intervals_icu_sync import INTERVALS_BASE_URL, _build_auth


def test_build_auth_uses_api_key_username_form():
    """HTTP Basic auth: username is literal 'API_KEY', password is user PAT.

    Verified V1 against live API on 2026-04-22. The alternate form
    (username=athlete_id) returned 403.
    """
    auth = _build_auth({"athlete_id": "i123456", "api_key": "secret-pat"})
    assert auth == ("API_KEY", "secret-pat")
