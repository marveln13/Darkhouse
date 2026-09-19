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
