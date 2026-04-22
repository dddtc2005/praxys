from unittest.mock import MagicMock, patch

import pytest

from sync.intervals_icu_sync import INTERVALS_BASE_URL, _build_auth, _request


def test_build_auth_uses_api_key_username_form():
    """HTTP Basic auth: username is literal 'API_KEY', password is user PAT.

    Verified V1 against live API on 2026-04-22. The alternate form
    (username=athlete_id) returned 403.
    """
    auth = _build_auth({"athlete_id": "i123456", "api_key": "secret-pat"})
    assert auth == ("API_KEY", "secret-pat")


def _mock_response(status_code: int = 200, json_payload=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_payload or {}
    if status_code >= 400:
        def _raise():
            from requests import HTTPError
            raise HTTPError(response=resp)
        resp.raise_for_status.side_effect = _raise
    else:
        resp.raise_for_status.return_value = None
    return resp


@patch("sync.intervals_icu_sync.requests.get")
def test_request_returns_json_on_200(mock_get):
    mock_get.return_value = _mock_response(200, {"ok": True})
    result = _request("/athlete/i1", credentials={"athlete_id": "i1", "api_key": "k"})
    assert result == {"ok": True}
    mock_get.assert_called_once()
    call_kwargs = mock_get.call_args.kwargs
    assert call_kwargs["auth"] == ("API_KEY", "k")
    assert call_kwargs["timeout"] == 15
    assert "praxys" in call_kwargs["headers"]["User-Agent"]


@patch("sync.intervals_icu_sync.requests.get")
def test_request_401_raises_unauthorized(mock_get):
    from sync.intervals_icu_sync import IntervalsIcuUnauthorized
    mock_get.return_value = _mock_response(401)
    with pytest.raises(IntervalsIcuUnauthorized):
        _request("/athlete/i1", credentials={"athlete_id": "i1", "api_key": "k"})


@patch("sync.intervals_icu_sync.time.sleep")
@patch("sync.intervals_icu_sync.requests.get")
def test_request_429_retries_with_backoff(mock_get, mock_sleep):
    mock_get.side_effect = [
        _mock_response(429),
        _mock_response(429),
        _mock_response(200, {"ok": True}),
    ]
    result = _request("/athlete/i1", credentials={"athlete_id": "i1", "api_key": "k"})
    assert result == {"ok": True}
    assert mock_get.call_count == 3
    assert mock_sleep.call_args_list[0].args[0] == 1.0
    assert mock_sleep.call_args_list[1].args[0] == 2.0


@patch("sync.intervals_icu_sync.time.sleep")
@patch("sync.intervals_icu_sync.requests.get")
def test_request_429_exhausts_retries(mock_get, mock_sleep):
    from sync.intervals_icu_sync import IntervalsIcuRateLimited
    mock_get.return_value = _mock_response(429)
    with pytest.raises(IntervalsIcuRateLimited):
        _request("/athlete/i1", credentials={"athlete_id": "i1", "api_key": "k"})
    assert mock_get.call_count == 4  # MAX_RETRIES
