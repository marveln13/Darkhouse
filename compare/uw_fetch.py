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


def _print_key(p):
    # tracking_id alone is NOT unique per print (verified live), so it can't be the dedupe key.
    return (p.executed_at, p.size, p.price, p.tracking_id)


def fetch_dark_pool_day(client, ticker, date, min_size=None, page_limit=500, max_pages=20):
    """Regular-hours prints for one ET date. Verified live: once `older_than`
    is set the API stops honouring `date`, so a naive pager walks back into
    prior days (asking for 9/18 returned 9/15-9/18) -- results are filtered to
    `date` and paging stops as soon as a page reaches an earlier day."""
    seen, out, cursor = set(), [], None
    for _ in range(max_pages):
        page = darkpool.ticker_prints(client, ticker, limit=page_limit, min_size=min_size,
                                      date=date, older_than=cursor)
        fresh = [p for p in page if _print_key(p) not in seen]
        seen.update(_print_key(p) for p in fresh)
        out.extend(p for p in fresh
                   if et_date(_dt(p.executed_at)) == date and is_regular_hours(_dt(p.executed_at)))
        if len(page) < page_limit or not fresh:
            break
        new_cursor = min(p.executed_at for p in page)
        if new_cursor == cursor or et_date(_dt(new_cursor)) < date:
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
