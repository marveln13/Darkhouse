from src import flow


def test_flow_alerts_parses_and_flags_bullish_skew(fake_client):
    alerts = flow.flow_alerts(fake_client, ticker="SPY")

    assert len(alerts) == 3
    call_alert = next(a for a in alerts if a.type == "call")
    assert call_alert.is_bullish_skewed is True  # ask-side buying on a call

    put_sold = next(a for a in alerts if a.type == "put" and a.strike == 435.00)
    assert put_sold.is_bullish_skewed is True  # bid-side selling on a put

    put_bought = next(a for a in alerts if a.type == "put" and a.strike == 440.00)
    assert put_bought.is_bullish_skewed is False  # ask-side buying on a put
