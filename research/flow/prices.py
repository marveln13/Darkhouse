"""
Daily closes for the underlying tickers and SPY, from Alpaca (split-adjusted),
cached per ticker under the gitignored .cache/. Credentials are read from the
sibling ARGUS checkout's .env at call time and never printed or stored.
"""
import json
import os
from datetime import datetime, timezone

from dotenv import dotenv_values

from compare.argus_logs import ET

BATCH = 100


def alpaca_keys(argus_root):
    values = dotenv_values(os.path.join(argus_root, ".env"))
    return values["ALPACA_API_KEY"], values["ALPACA_SECRET_KEY"]


def bars_to_closes(bars):
    """{ET date: close} from Alpaca bar objects (daily bars are stamped at ET midnight)."""
    return {b.timestamp.astimezone(ET).date().isoformat(): float(b.close) for b in bars}


def fetch_daily_closes(tickers, start, end, keys, cache_dir):
    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    os.makedirs(cache_dir, exist_ok=True)
    out, missing = {}, []
    for t in tickers:
        path = os.path.join(cache_dir, f"{t}.json")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                out[t] = json.load(f)
        else:
            missing.append(t)

    client = StockHistoricalDataClient(*keys)
    for i in range(0, len(missing), BATCH):
        batch = missing[i:i + BATCH]
        got = client.get_stock_bars(StockBarsRequest(
            symbol_or_symbols=batch, timeframe=TimeFrame.Day, adjustment=Adjustment.SPLIT, feed=DataFeed.SIP,
            start=datetime.fromisoformat(start).replace(tzinfo=timezone.utc),
            end=datetime.fromisoformat(end).replace(tzinfo=timezone.utc)))
        for t in batch:
            closes = bars_to_closes(got.data.get(t, []))
            out[t] = closes
            with open(os.path.join(cache_dir, f"{t}.json"), "w", encoding="utf-8") as f:
                json.dump(closes, f)
    return out
