import pytest

from src.uw_client import UnusualWhalesClient, UnusualWhalesAuthError


def test_missing_key_raises_auth_error(monkeypatch):
    monkeypatch.delenv("UNUSUAL_WHALES_API_KEY", raising=False)
    with pytest.raises(UnusualWhalesAuthError):
        UnusualWhalesClient()


def test_placeholder_key_raises_auth_error(monkeypatch):
    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", "your_unusual_whales_api_key")
    with pytest.raises(UnusualWhalesAuthError):
        UnusualWhalesClient()


def test_real_key_sets_bearer_header(monkeypatch):
    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", "real-trial-key-123")
    client = UnusualWhalesClient()
    assert client.session.headers["Authorization"] == "Bearer real-trial-key-123"
    assert client.session.headers["UW-CLIENT-API-ID"] == "100001"


class _Resp:
    def __init__(self, status, body=None):
        self.status_code, self.headers, self._body = status, {}, body or {"data": []}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(response=self)

    def json(self):
        return self._body


def _client(monkeypatch, responses):
    import requests
    monkeypatch.setenv("UNUSUAL_WHALES_API_KEY", "real-trial-key-123")
    monkeypatch.setattr("src.uw_client.TRANSIENT_RETRY_SECONDS", 0)
    client = UnusualWhalesClient()
    seq = iter(responses)

    def fake_get(url, params=None, timeout=None):
        r = next(seq)
        if isinstance(r, Exception):
            raise r
        return r
    client.session.get = fake_get
    return client, requests


def test_one_retry_on_a_5xx(monkeypatch):
    client, _ = _client(monkeypatch, [_Resp(502), _Resp(200, {"data": [1]})])
    assert client.get("/x") == {"data": [1]}


def test_one_retry_on_a_dropped_connection(monkeypatch):
    import requests
    client, _ = _client(monkeypatch, [requests.ConnectionError("reset"), _Resp(200, {"data": [2]})])
    assert client.get("/x") == {"data": [2]}


def test_a_second_5xx_still_raises(monkeypatch):
    import requests
    client, _ = _client(monkeypatch, [_Resp(503), _Resp(503)])
    with pytest.raises(requests.HTTPError):
        client.get("/x")


def test_4xx_is_not_retried(monkeypatch):
    import requests
    client, _ = _client(monkeypatch, [_Resp(422), _Resp(200)])
    with pytest.raises(requests.HTTPError):
        client.get("/x")
