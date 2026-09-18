from src import darkpool, gex, flow, analysis


def test_block_prints_filters_by_notional_and_excludes_canceled(fake_client):
    prints = darkpool.ticker_prints(fake_client, "SPY")
    blocks = analysis.block_prints(prints, notional_floor=200_000)

    # Only the first print (5000@441.50=$2.2M) clears the floor and isn't
    # canceled; the 10000@441.72 print is a bigger notional but canceled.
    assert len(blocks) == 1
    assert blocks[0].tracking_id == 1001


def test_price_level_confluence_flags_levels_near_gex_structure(fake_client):
    levels = darkpool.price_levels(fake_client, "SPY")
    gex_data = gex.gex_levels(fake_client, "SPY")

    hits = analysis.price_level_confluence(levels, gex_data, proximity_pct=0.5)

    assert len(hits) == 3
    by_price = {h["price"]: h for h in hits}
    assert by_price[440.00]["gex_level"] == "gamma_flip"
    assert by_price[445.00]["gex_level"] == "call_wall"


def test_price_level_confluence_respects_tighter_proximity(fake_client):
    levels = darkpool.price_levels(fake_client, "SPY")
    gex_data = gex.gex_levels(fake_client, "SPY")

    hits = analysis.price_level_confluence(levels, gex_data, proximity_pct=0.05)

    assert len(hits) == 1  # only the 440.00/gamma_flip(440.10) pair is this tight


def test_flow_bias_is_bullish_when_bullish_premium_dominates(fake_client):
    alerts = flow.flow_alerts(fake_client, ticker="SPY")
    bias = analysis.flow_bias(alerts)

    assert bias["n"] == 3
    assert bias["net_bias"] == "bullish"
    assert bias["bullish_premium"] == 660_000.0
    assert bias["bearish_premium"] == 150_000.0
    assert bias["sweep_count"] == 2


def test_flow_bias_handles_empty_input():
    bias = analysis.flow_bias([])
    assert bias["n"] == 0
    assert bias["net_bias"] == "flat"


def test_top_gamma_strikes_ranks_by_absolute_net_and_respects_source(fake_client):
    rows = gex.spot_gex_by_strike(fake_client, "SPY")

    by_vol = analysis.top_gamma_strikes(rows, source="vol", n=2)
    assert [r.strike for r in by_vol] == [445.0, 440.0]  # |-300M|, |200M|

    by_oi = analysis.top_gamma_strikes(rows, source="oi", n=2)
    assert [r.strike for r in by_oi] == [450.0, 445.0]   # 400M, 150M
