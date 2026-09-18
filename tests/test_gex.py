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
