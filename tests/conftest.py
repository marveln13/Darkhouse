import json
import os

import pytest

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def load_fixture(name):
    with open(os.path.join(FIXTURES_DIR, name)) as f:
        return json.load(f)


class FakeClient:
    """Stands in for UnusualWhalesClient -- returns a canned fixture for
    whatever path is requested, so parsing/analysis logic is verified
    against the real documented response shape without a live API key."""

    def __init__(self, responses):
        self.responses = responses  # {path: fixture_dict}
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        if path not in self.responses:
            raise KeyError(f"No fixture registered for path {path}")
        return self.responses[path]


@pytest.fixture
def fake_client():
    return FakeClient({
        "/api/darkpool/SPY": load_fixture("darkpool_ticker.json"),
        "/api/darkpool/SPY/price-levels": load_fixture("darkpool_price_levels.json"),
        "/api/stock/SPY/gex-levels": load_fixture("gex_levels.json"),
        "/api/stock/SPY/spot-exposures/strike": load_fixture("spot_gex_by_strike.json"),
        "/api/option-trades/flow-alerts": load_fixture("flow_alerts.json"),
        "/api/stock/SPY/ohlc/5m": load_fixture("ohlc_5m.json"),
    })
