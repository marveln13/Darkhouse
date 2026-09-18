"""GET /api/stock/{ticker}/gex-levels"""
from .models import GexLevels


def gex_levels(client, ticker, date=None, source="vol"):
    params = {"source": source}
    if date is not None:
        params["date"] = date
    raw = client.get(f"/api/stock/{ticker}/gex-levels", params=params)
    return GexLevels.from_api(ticker, raw)
