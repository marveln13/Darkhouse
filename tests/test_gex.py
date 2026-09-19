from src import gex


def test_gex_levels_parses_walls_and_flip(fake_client):
    levels = gex.gex_levels(fake_client, "SPY")

    assert levels.ticker == "SPY"
    assert levels.call_wall == 445.50
    assert levels.put_wall == 400.00
    assert levels.gamma_flip == 440.10
    assert levels.gamma_magnet == 460.00
    assert levels.nearby_flips == [438.00, 440.10, 443.00]


def test_gex_levels_passes_source_param(fake_client):
    gex.gex_levels(fake_client, "SPY", source="oi")
    path, params = fake_client.calls[-1]
    assert params["source"] == "oi"


def test_spot_gex_by_strike_parses_rows_and_windows_params(fake_client):
    rows = gex.spot_gex_by_strike(fake_client, "SPY", min_strike=430, max_strike=455)

    assert [r.strike for r in rows] == [435.0, 440.0, 445.0, 450.0]
    path, params = fake_client.calls[-1]
    assert path == "/api/stock/SPY/spot-exposures/strike"
    assert params == {"limit": 500, "min_strike": 430, "max_strike": 455}


def test_strike_net_gamma_by_source(fake_client):
    row = next(r for r in gex.spot_gex_by_strike(fake_client, "SPY") if r.strike == 445.0)
    assert row.net("vol") == -300_000_000.0   # 150M call + (-450M) put
    assert row.net("oi") == 150_000_000.0     # 200M call + (-50M) put


def test_strike_request_always_asks_for_500_because_the_real_default_page_is_50_low_strikes(fake_client):
    gex.spot_gex_by_strike(fake_client, "SPY")
    assert fake_client.calls[-1][1]["limit"] == 500


class CappedClient:
    """First call returns a full (capped) page of far strikes; the windowed
    refetch returns just the strikes near spot."""

    def __init__(self):
        self.calls = []

    def get(self, path, params=None):
        self.calls.append(dict(params))
        if "min_strike" not in params:
            return {"data": [{"strike": str(50 + i * 0.5), "price": "760.0"} for i in range(500)]}
        return {"data": [{"strike": "760", "price": "760.0", "call_gamma_oi": "1", "put_gamma_oi": "-2"}]}


def test_capped_page_triggers_a_refetch_windowed_around_spot():
    client = CappedClient()
    rows = gex.spot_gex_by_strike(client, "SPY", near_spot_pct=10.0)

    assert len(client.calls) == 2
    assert abs(client.calls[1]["min_strike"] - 684.0) < 1e-6 and abs(client.calls[1]["max_strike"] - 836.0) < 1e-6
    assert [r.strike for r in rows] == [760.0]


def test_gex_levels_reads_the_real_nested_data_shape(fake_client):
    levels = gex.gex_levels(fake_client, "SPY")
    assert levels.call_wall == 445.50 and levels.gamma_flip == 440.10   # would be None if parsed at top level
