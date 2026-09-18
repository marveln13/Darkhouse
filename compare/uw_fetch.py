"""
Paginated UW pulls for one ticker-day. Both endpoints return newest-first
and accept `older_than`, so paging walks the cursor back to the start of the
day. Guards: a page cap (API budget) and a stalled-cursor check.
"""
from datetime import datetime, timedelta

from src import darkpool, flow

from .argus_logs import ET, et_date, is_regular_hours


def _dt(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def fetch_dark_pool_day(client, ticker, date, min_size=None, page_limit=500, max_pages=20):
    seen, out, cursor = set(), [], None
    for _ in range(max_pages):
        page = darkpool.ticker_prints(client, ticker, limit=page_limit, min_size=min_size,
                                      date=date, older_than=cursor)
        fresh = [p for p in page if p.tracking_id not in seen]
        seen.update(p.tracking_id for p in fresh)
        out.extend(p for p in fresh if is_regular_hours(_dt(p.executed_at)))
        if len(page) < page_limit or not fresh:
            break
        new_cursor = min(p.executed_at for p in page)
        if new_cursor == cursor:
            break
        cursor = new_cursor
    return out


def fetch_flow_alerts_day(client, ticker, date, page_limit=200, max_pages=20):
    """Regular-hours flow alerts for one ticker on one ET date."""
    start = datetime.fromisoformat(date).replace(tzinfo=ET)
    day_start = start.isoformat()
    seen, out, cursor = set(), [], (start + timedelta(days=1)).isoformat()
    for _ in range(max_pages):
        page = flow.flow_alerts(client, ticker=ticker, limit=page_limit,
                                newer_than=day_start, older_than=cursor)
        keys = [(a.created_at, a.strike, a.type, a.expiry, a.total_premium) for a in page]
        fresh = [a for a, k in zip(page, keys) if k not in seen]
        seen.update(keys)
        out.extend(a for a in fresh if is_regular_hours(_dt(a.created_at)) and et_date(_dt(a.created_at)) == date)
        if len(page) < page_limit or not fresh:
            break
        new_cursor = min(a.created_at for a in page)
        if new_cursor == cursor:
            break
        cursor = new_cursor
    return out
