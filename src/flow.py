"""GET /api/option-trades/flow-alerts"""
from .models import FlowAlert


def flow_alerts(client, ticker=None, limit=100, min_premium=None, is_sweep=None, unusual=None):
    params = {"limit": limit}
    if ticker is not None:
        params["ticker_symbol"] = ticker
    if min_premium is not None:
        params["min_premium"] = min_premium
    if is_sweep is not None:
        params["is_sweep"] = is_sweep
    if unusual is not None:
        params["unusual"] = unusual
    raw = client.get("/api/option-trades/flow-alerts", params=params)
    return [FlowAlert.from_api(r) for r in raw.get("data", raw)]
