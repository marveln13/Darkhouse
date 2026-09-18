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
    assert params == {"min_strike": 430, "max_strike": 455}


def test_strike_net_gamma_by_source(fake_client):
    row = next(r for r in gex.spot_gex_by_strike(fake_client, "SPY") if r.strike == 445.0)
    assert row.net("vol") == -300_000_000.0   # 150M call + (-450M) put
    assert row.net("oi") == 150_000_000.0     # 200M call + (-50M) put
