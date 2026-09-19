from scripts import first_call_check
from tests.conftest import FakeClient, load_fixture


def _client():
    darkpool = load_fixture("darkpool_ticker.json")
    return FakeClient({
        "/api/darkpool/recent": darkpool,
        "/api/darkpool/SPY": darkpool,
        "/api/darkpool/SPY/price-levels": load_fixture("darkpool_price_levels.json"),
        "/api/stock/SPY/gex-levels": load_fixture("gex_levels.json"),
        "/api/stock/SPY/spot-exposures/strike": load_fixture("spot_gex_by_strike.json"),
        "/api/stock/SPY/greek-exposure": {"data": [
            {"date": "2026-09-16", "call_gamma": "5e9", "put_gamma": "-7e9"},
            {"date": "2026-09-17", "call_gamma": "6e9", "put_gamma": "-2e9"}]},
        "/api/option-trades/flow-alerts": load_fixture("flow_alerts.json"),
    })


def test_first_call_check_runs_every_section_and_reports_sign_and_timeframes(capsys):
    first_call_check.main(_client(), "SPY")
    out = capsys.readouterr().out

    assert "FAILED" not in out and "HTTP" not in out
    assert "put_gamma_oi : 100% of 4 negative" in out          # fixture puts are signed negative
    assert "timeframe=YTD" in out and "2026-09-16 .. 2026-09-17" in out
    assert "price*size=" in out and "rows returned: 4" in out


def test_one_failing_endpoint_does_not_hide_the_others(capsys):
    client = _client()
    del client.responses["/api/stock/SPY/gex-levels"]
    first_call_check.main(client, "SPY")
    out = capsys.readouterr().out

    assert "FAILED: KeyError" in out
    assert "spot-exposures/strike" in out and "rows returned: 4" in out
