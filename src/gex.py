"""GET /api/stock/{ticker}/gex-levels, /api/stock/{ticker}/spot-exposures/strike"""
from .models import GexLevels, StrikeGamma


def gex_levels(client, ticker, date=None, source="vol"):
    params = {"source": source}
    if date is not None:
        params["date"] = date
    raw = client.get(f"/api/stock/{ticker}/gex-levels", params=params)
    return GexLevels.from_api(ticker, raw)


def spot_gex_by_strike(client, ticker, date=None, min_strike=None, max_strike=None):
    """Per-strike gamma. Returns up to the endpoint's 500-row default page;
    use min_strike/max_strike to window around spot for wide chains."""
    params = {}
    if date is not None:
        params["date"] = date
    if min_strike is not None:
        params["min_strike"] = min_strike
    if max_strike is not None:
        params["max_strike"] = max_strike
    raw = client.get(f"/api/stock/{ticker}/spot-exposures/strike", params=params)
    return [StrikeGamma.from_api(r) for r in raw.get("data", raw)]
