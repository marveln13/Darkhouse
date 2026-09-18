from src import darkpool


def test_ticker_prints_parses_real_documented_fields(fake_client):
    prints = darkpool.ticker_prints(fake_client, "SPY")

    assert len(prints) == 3
    p = prints[0]
    assert p.ticker == "SPY"
    assert p.price == 441.50
    assert p.size == 5000
    assert p.notional == 441.50 * 5000
    assert p.canceled is False


def test_ticker_prints_includes_canceled_trades_so_analysis_can_filter(fake_client):
    prints = darkpool.ticker_prints(fake_client, "SPY")
    assert any(p.canceled for p in prints)


def test_price_levels_computes_dark_pool_share(fake_client):
    levels = darkpool.price_levels(fake_client, "SPY")

    assert levels.ticker == "SPY"
    assert levels.date == "2026-09-18"
    assert len(levels.levels) == 3
    # 900000 dark / (900000+100000) regular = 90%
    assert levels.levels[0].dark_pool_share_pct == 90.0
