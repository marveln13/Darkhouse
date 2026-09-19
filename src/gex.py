"""GET /api/stock/{ticker}/gex-levels, /api/stock/{ticker}/spot-exposures/strike"""
from .models import DailyGreekExposure, GexLevels, StrikeGamma


def gex_levels(client, ticker, date=None, source="vol"):
    params = {"source": source}
    if date is not None:
        params["date"] = date
    raw = client.get(f"/api/stock/{ticker}/gex-levels", params=params)
    return GexLevels.from_api(ticker, raw.get("data", raw))


def spot_gex_by_strike(client, ticker, date=None, min_strike=None, max_strike=None,
                       limit=500, near_spot_pct=10.0):
    """Per-strike gamma. Verified live: the endpoint's real default page is 50
    rows of the LOWEST strikes (SPY at $763 returned strikes 50-295), so
    `limit=500` is always sent. If even that is capped, refetch a window of
    +/-near_spot_pct around the underlying price carried in the rows."""
    params = {"limit": limit}
    if date is not None:
        params["date"] = date
    if min_strike is not None:
        params["min_strike"] = min_strike
    if max_strike is not None:
        params["max_strike"] = max_strike
    rows = client.get(f"/api/stock/{ticker}/spot-exposures/strike", params=params)
    rows = rows.get("data", rows)
    if len(rows) >= limit and min_strike is None and max_strike is None and rows[0].get("price"):
        spot = float(rows[0]["price"])
        params["min_strike"] = spot * (1 - near_spot_pct / 100.0)
        params["max_strike"] = spot * (1 + near_spot_pct / 100.0)
        rows = client.get(f"/api/stock/{ticker}/spot-exposures/strike", params=params)
        rows = rows.get("data", rows)
    return [StrikeGamma.from_api(r) for r in rows]


def greek_exposure_history(client, ticker, timeframe=None, date=None):
    """GET /api/stock/{ticker}/greek-exposure -- daily call/put gamma, one
    row per date. Verified live: no timeframe = last year (250 rows); valid
    timeframes are single tokens 1D 2D 1W 2W 1M 2M 1Y 2Y and YTD (2Y = 500
    rows). The docs' "1M-2M" style is NOT valid input (HTTP 422)."""
    params = {}
    if timeframe is not None:
        params["timeframe"] = timeframe
    if date is not None:
        params["date"] = date
    raw = client.get(f"/api/stock/{ticker}/greek-exposure", params=params)
    return [DailyGreekExposure.from_api(r) for r in raw.get("data", raw)]
