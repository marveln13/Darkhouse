"""
GET /api/darkpool/recent, /api/darkpool/{ticker}, /api/darkpool/{ticker}/price-levels
"""
from .models import DarkPoolPrint, DarkPoolPriceLevels


def recent_prints(client, limit=100, min_premium=None, min_size=None, date=None):
    params = {"limit": limit}
    if min_premium is not None:
        params["min_premium"] = min_premium
    if min_size is not None:
        params["min_size"] = min_size
    if date is not None:
        params["date"] = date
    raw = client.get("/api/darkpool/recent", params=params)
    return [DarkPoolPrint.from_api(r) for r in raw.get("data", raw)]


def ticker_prints(client, ticker, limit=500, min_premium=None, min_size=None, date=None):
    params = {"limit": limit}
    if min_premium is not None:
        params["min_premium"] = min_premium
    if min_size is not None:
        params["min_size"] = min_size
    if date is not None:
        params["date"] = date
    raw = client.get(f"/api/darkpool/{ticker}", params=params)
    return [DarkPoolPrint.from_api(r) for r in raw.get("data", raw)]


def price_levels(client, ticker, date=None):
    params = {"date": date} if date else {}
    raw = client.get(f"/api/darkpool/{ticker}/price-levels", params=params)
    return DarkPoolPriceLevels.from_api(ticker, raw)
