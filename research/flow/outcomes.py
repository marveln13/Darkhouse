"""
Outcome measurement exactly as registered in protocol.py. Pure functions over
already-fetched data: no network, no tuning knobs beyond the protocol's.
"""
from research.flow import protocol


def calendar_index(spy_closes):
    cal = sorted(spy_closes)
    return cal, {d: i for i, d in enumerate(cal)}


def shift(cal, index, date, n):
    i = index.get(date)
    return cal[i + n] if i is not None and 0 <= i + n < len(cal) else None


def underlying_outcome(date, sign, closes, spy_closes, cal, index, horizon=protocol.UNDERLYING_HORIZON_DAYS):
    """Direction-signed return of the underlying, close of D -> close of D+horizon, minus SPY."""
    end = shift(cal, index, date, horizon)
    if end is None:
        return None
    c0, c1, s0, s1 = closes.get(date), closes.get(end), spy_closes.get(date), spy_closes.get(end)
    if not (c0 and c1 and s0 and s1):
        return None
    return sign * ((c1 / c0 - 1.0) - (s1 / s0 - 1.0))


def half_spread(row):
    if not row:
        return None
    try:
        bid, ask = float(row["nbbo_bid"]), float(row["nbbo_ask"])
    except (KeyError, TypeError, ValueError):
        return None
    if ask <= 0 or bid < 0 or ask < bid or ask + bid <= 0:
        return None
    return (ask - bid) / (ask + bid)


def contract_outcome(date, rows_by_date, cal, index, exit_days=protocol.CONTRACT_EXIT_DAYS):
    """Buy the same contract: D+1 open_price -> D+1+exit_days avg_price. Returns a dict with a status."""
    entry_day, exit_day = shift(cal, index, date, 1), shift(cal, index, date, 1 + exit_days)
    if entry_day is None or exit_day is None:
        return {"status": "no_calendar"}
    er, xr = rows_by_date.get(entry_day), rows_by_date.get(exit_day)
    if er is None or xr is None:
        return {"status": "no_row"}
    entry, exit_ = float(er["open_price"]), float(xr["avg_price"])
    if entry < protocol.MIN_ENTRY_PRICE:
        return {"status": "sub_dime"}
    gross = exit_ / entry - 1.0
    hs = half_spread(rows_by_date.get(date))
    net = None if hs is None else exit_ * (1 - hs) / (entry * (1 + hs)) - 1.0
    return {"status": "ok", "gross": gross, "net": net, "half_spread": hs}
