"""
Loaders for ARGUS's own on-disk data, so the UW comparison reads exactly
what ARGUS recorded. Read-only. The live JSONL logs are appended to by a
running process and can contain torn or zeroed lines (the 2026-09-16 power
outage left a run of NUL bytes in dark_pool_blocks.jsonl), so loading
counts and skips bad lines instead of failing.
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def load_jsonl_tolerant(path):
    rows, bad = [], 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                bad += 1
    return rows, bad


def _with_utc(rows):
    out = []
    for r in rows:
        try:
            r["dt"] = datetime.fromisoformat(r["ts"])
        except (KeyError, ValueError):
            continue
        out.append(r)
    return out


def load_dark_pool_blocks(path):
    rows, bad = load_jsonl_tolerant(path)
    return _with_utc(rows), bad


def load_flow_snapshots(path):
    rows, bad = load_jsonl_tolerant(path)
    return _with_utc(rows), bad


def load_gex_cache(path):
    """ARGUS's cached per-date SPY GEX: {trading_date: {gex, prior_day, bucket}}.
    A date's value was computed from the PRIOR trading day's end-of-day
    Greeks/OI, so compare it to UW's gamma for `prior_day`, not the key."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def et_date(dt):
    return dt.astimezone(ET).date().isoformat()


def is_regular_hours(dt):
    t = dt.astimezone(ET)
    return (t.hour, t.minute) >= (9, 30) and t.hour < 16


def regular_hours_counts_by_day(blocks):
    """Blocks per ET trading day inside 09:30-16:00. A day with ~0 means the
    detector was down -- comparing against UW on that day measures the
    outage, not the signals."""
    counts = {}
    for b in blocks:
        if is_regular_hours(b["dt"]):
            counts[et_date(b["dt"])] = counts.get(et_date(b["dt"]), 0) + 1
    return counts


def alive_minutes(blocks):
    """ET minutes in which ARGUS logged at least one block on ANY ticker. The
    detector normally logs ~100/min across ~116 tickers, so an empty minute
    means it was down (e.g. the 2026-09-16 power outage), not that nothing
    traded -- comparing UW against those minutes would measure the outage."""
    return {b["dt"].astimezone(ET).strftime("%Y-%m-%d %H:%M") for b in blocks}
