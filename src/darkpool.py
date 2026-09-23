"""
GET /api/darkpool/recent, /api/darkpool/{ticker}, /api/darkpool/{ticker}/price-levels
"""
from datetime import datetime, time
from zoneinfo import ZoneInfo

from .models import DarkPoolPrint, DarkPoolPriceLevels

ET = ZoneInfo("America/New_York")
REGULAR_OPEN, REGULAR_CLOSE = time(9, 30), time(16, 0)


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


def ticker_prints(client, ticker, limit=500, min_premium=None, min_size=None, date=None,
                  newer_than=None, older_than=None):
    params = {"limit": limit}
    if min_premium is not None:
        params["min_premium"] = min_premium
    if min_size is not None:
        params["min_size"] = min_size
    if date is not None:
        params["date"] = date
    if newer_than is not None:
        params["newer_than"] = newer_than
    if older_than is not None:
        params["older_than"] = older_than
    raw = client.get(f"/api/darkpool/{ticker}", params=params)
    return [DarkPoolPrint.from_api(r) for r in raw.get("data", raw)]


def price_levels(client, ticker, date=None):
    params = {"date": date} if date else {}
    raw = client.get(f"/api/darkpool/{ticker}/price-levels", params=params)
    return DarkPoolPriceLevels.from_api(ticker, raw)


def _et(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ET)


def _print_key(p):
    # tracking_id alone is NOT unique per print (verified live), so it can't be the dedupe key.
    return (p.executed_at, p.size, p.price, p.tracking_id)


def prints_for_day(client, ticker, date, min_premium=None, page_limit=500, max_pages=10, regular_hours=True):
    """All prints for one ET trading date, newest-first pages walked back with `older_than`.
    Verified live: once `older_than` is set the API stops honouring `date` and walks into earlier days, so results
    are filtered to `date` and paging stops at the day boundary. `min_premium` filters server-side (far fewer pages
    for liquid tickers). Returns (prints, complete) -- complete is False when max_pages ran out before the session
    start, i.e. the earliest part of the day is missing."""
    seen, out, cursor = set(), [], None
    for _ in range(max_pages):
        page = ticker_prints(client, ticker, limit=page_limit, min_premium=min_premium, date=date, older_than=cursor)
        fresh = [p for p in page if _print_key(p) not in seen]
        seen.update(_print_key(p) for p in fresh)
        for p in fresh:
            t = _et(p.executed_at)
            if t.date().isoformat() == date and (not regular_hours or REGULAR_OPEN <= t.time() < REGULAR_CLOSE):
                out.append(p)
        if len(page) < page_limit or not fresh:
            return out, True
        new_cursor = min(p.executed_at for p in page)
        if new_cursor == cursor or _et(new_cursor).date().isoformat() < date:
            return out, True
        cursor = new_cursor
    return out, False
