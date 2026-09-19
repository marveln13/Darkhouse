"""Read ARGUS's cached M30 bars (read-only). Timestamps are UTC bar starts."""
import json
import os
from datetime import datetime

from compare.argus_logs import ET


def load_m30(argus_root, ticker):
    path = os.path.join(argus_root, "backtest", "data_cache", f"{ticker}_M30.json")
    with open(path, encoding="utf-8") as f:
        bars = json.load(f)["bars"]
    for b in bars:
        b["dt"] = datetime.strptime(b["timestamp"], "%Y-%m-%dT%H:%M:%S.000%z").astimezone(ET)
        b["date"] = b["dt"].date().isoformat()
    bars.sort(key=lambda b: b["dt"])
    return bars


def day_ranges(bars):
    """{date: (start_idx, end_idx_exclusive)} over a continuous bar list."""
    ranges = {}
    for i, b in enumerate(bars):
        start, _ = ranges.get(b["date"], (i, i))
        ranges[b["date"]] = (start, i + 1)
    return ranges
