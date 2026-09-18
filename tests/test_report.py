from src import darkpool, gex, flow, analysis, report


def _render(fake_client, ticker="SPY"):
    prints = darkpool.ticker_prints(fake_client, "SPY")
    levels = darkpool.price_levels(fake_client, "SPY")
    gex_data = gex.gex_levels(fake_client, "SPY")
    alerts = flow.flow_alerts(fake_client, ticker="SPY")
    blocks = analysis.block_prints(prints)
    confluence = analysis.price_level_confluence(levels, gex_data)
    bias = analysis.flow_bias(alerts)
    return report.render_html(ticker, gex_data, levels, blocks, confluence, bias, 200_000)


def test_report_contains_all_sections_and_gex_levels(fake_client):
    page = _render(fake_client)

    assert "SPY" in page
    for label in ("Call wall", "Put wall", "Gamma flip", "Gamma magnet"):
        assert label in page
    assert "BULLISH" in page
    assert "$2,207,500" in page  # the one qualifying block print's notional


def test_report_ladder_orders_prices_descending(fake_client):
    page = _render(fake_client)
    assert page.index("$460.00") < page.index("$445.50") < page.index("$440.10") < page.index("$400.00")


def test_report_escapes_untrusted_ticker(fake_client):
    page = _render(fake_client, ticker="<script>x</script>")
    assert "<script>x</script>" not in page
    assert "&lt;script&gt;" in page
