"""
Step 1 of the implementation checklist: export the M30i PUTS signal table from the ARGUS repo.

    python -m research.argus_filter.signals [--argus-root PATH]

Population, exactly as ARGUS builds it (research/argus_filter/PREREGISTRATION.md, "Population"):
`find_signals_with_all_factors` per ticker -> keep rvol_20 >= RVOL_20_LOUD_THRESHOLD -> `dedup_earliest`
-> mirrored to a put (stop = entry + |entry - original stop|, target = 3R below entry) -> outcome from
`trade_simulator.simulate_trade` with HOLD_BARS, all imported from the ARGUS checkout, not re-implemented.

Two files are written to .cache/argus_filter/ (gitignored, never committed):
  signal_keys.csv  ticker, date, prior_date, entry_ts            -- NO outcomes; the fetch reads only this
  signals.csv      the keys + entry, stop, target, risk, r       -- read only by analyze.py
so the fetch script cannot see outcomes even by accident. R is computed here but never printed.
"""
import argparse
import bisect
import csv
import json
import os
import subprocess
import sys
from collections import Counter, namedtuple
from datetime import date as date_cls, timedelta

from compare.argus_logs import ET
from research.argus_filter import protocol

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_ARGUS_ROOT = os.path.join(REPO_ROOT, "..", "ai-trading-desk-2")
CACHE_DIR = os.path.join(REPO_ROOT, ".cache", protocol.CACHE_SUBDIR)

KEY_COLUMNS = ("ticker", "date", "prior_date", "entry_ts")
OUTCOME_COLUMNS = ("entry", "stop", "target", "risk", "r")
SIGNAL_COLUMNS = KEY_COLUMNS + OUTCOME_COLUMNS

# Everything the export needs from ARGUS, injectable so the pipeline is testable without the checkout.
Toolkit = namedtuple("Toolkit", "watchlist load_m30 atr_series find_signals dedup_earliest simulate_trade "
                                "parse_ts rvol_threshold target_r hold_bars")


def load_argus_toolkit(argus_root):
    """Import the real ARGUS functions. ARGUS goes AFTER this repo on sys.path so this repo's
    research/src/compare/scripts/tests names always win (ARGUS also has scripts/ and tests/)."""
    root = os.path.abspath(argus_root)
    if root not in sys.path:
        sys.path.insert(1, root)
    from backtest.test_liquidity_sweep_reversal_m30_quality_metrics import atr_series, load_cached_m30
    from backtest.test_m30_puts_win_factors import (HOLD_BARS, TARGET_R_MULTIPLE, dedup_earliest,
                                                    find_signals_with_all_factors)
    from backtest.trade_simulator import _parse_ts, simulate_trade
    from config import WATCHLIST
    from detection.liquidity_sweep_reversal_m30_engine import RVOL_20_LOUD_THRESHOLD
    return Toolkit(list(WATCHLIST), load_cached_m30, atr_series, find_signals_with_all_factors, dedup_earliest,
                   simulate_trade, _parse_ts, RVOL_20_LOUD_THRESHOLD, TARGET_R_MULTIPLE, HOLD_BARS)


def check_pinned(tk):
    """The document pins today's ARGUS values; refuse rather than silently build a different population."""
    drift = {name: (got, want) for name, got, want in (
        ("RVOL_20_LOUD_THRESHOLD", tk.rvol_threshold, protocol.PINNED_RVOL_20_LOUD_THRESHOLD),
        ("TARGET_R_MULTIPLE", tk.target_r, protocol.PINNED_TARGET_R_MULTIPLE),
        ("HOLD_BARS", tk.hold_bars, protocol.PINNED_HOLD_BARS)) if got != want}
    if drift:
        raise RuntimeError(f"ARGUS constants differ from the pre-registration (got, pinned): {drift}")


def et_date(tk, timestamp):
    return tk.parse_ts(timestamp).astimezone(ET).date().isoformat()


def prior_session(calendar, d):
    """The last trading session strictly before `d` in the sorted calendar, or None."""
    i = bisect.bisect_left(calendar, d)
    return calendar[i - 1] if i > 0 else None


def build_signals(tk, tickers=None, window_days=protocol.WINDOW_DAYS):
    """Returns (rows, calendar, stats). Rows are dicts with SIGNAL_COLUMNS."""
    check_pinned(tk)
    tickers = list(dict.fromkeys(tickers if tickers is not None else tk.watchlist))
    bars_by, loud, stats = {}, [], Counter()
    for t in tickers:
        bars = tk.load_m30(t)
        if not bars:
            stats["tickers_without_cache"] += 1
            continue
        bars_by[t] = bars
        for s in tk.find_signals(t, bars, tk.atr_series(bars)):
            stats["raw_signals"] += 1
            if (s.get("rvol_20") or 0) >= tk.rvol_threshold:
                loud.append(s)
    stats["tickers_used"] = len(bars_by)
    stats["loud_signals"] = len(loud)

    ts_by = {t: [tk.parse_ts(b["timestamp"]) for b in bars] for t, bars in bars_by.items()}
    calendar = sorted({ts.astimezone(ET).date().isoformat() for lst in ts_by.values() for ts in lst})
    end = date_cls.fromisoformat(calendar[-1])
    start = (end - timedelta(days=window_days)).isoformat()

    deduped = tk.dedup_earliest(loud)
    stats["deduped_signals"] = len(deduped)
    rows = []
    for s in sorted(deduped, key=lambda s: (s["timestamp"], s["ticker"])):
        d = et_date(tk, s["timestamp"])
        if d < start:
            stats["before_window"] += 1
            continue
        prior = prior_session(calendar, d)
        if prior is None:
            stats["no_prior_session"] += 1
            continue
        entry, orig_stop = s["entry_price"], s["stop_price"]
        raw_risk = entry - orig_stop
        if raw_risk == 0:
            stats["zero_risk"] += 1
            continue
        risk = abs(raw_risk)            # a gap through the original stop still mirrors -- as in the ARGUS put backtests
        stop = entry + risk
        r = tk.simulate_trade(bars_by[s["ticker"]], ts_by[s["ticker"]], s["entry_idx"], protocol.DIRECTION,
                              entry, stop, tk.target_r, max_bars_forward=tk.hold_bars)
        if r is None:
            stats["no_outcome"] += 1
            continue
        rows.append({"ticker": s["ticker"], "date": d, "prior_date": prior, "entry_ts": s["timestamp"],
                     "entry": entry, "stop": stop, "target": entry - tk.target_r * risk, "risk": risk, "r": r})
    stats["exported"] = len(rows)
    stats["window_start"], stats["window_end"] = start, calendar[-1]
    return rows, calendar, dict(stats)


def _write_csv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def write_exports(rows, calendar, meta, cache_dir=CACHE_DIR):
    os.makedirs(cache_dir, exist_ok=True)
    _write_csv(os.path.join(cache_dir, protocol.SIGNALS_FILE), SIGNAL_COLUMNS, rows)
    _write_csv(os.path.join(cache_dir, protocol.KEYS_FILE), KEY_COLUMNS, rows)
    with open(os.path.join(cache_dir, protocol.CALENDAR_FILE), "w", encoding="utf-8") as f:
        json.dump(calendar, f)
    with open(os.path.join(cache_dir, protocol.META_FILE), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def load_keys(cache_dir=CACHE_DIR):
    """Signal identities only -- the loader the fetch script uses. Cannot return an outcome."""
    with open(os.path.join(cache_dir, protocol.KEYS_FILE), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_signals(cache_dir=CACHE_DIR):
    """Signals WITH outcomes -- for analyze.py only."""
    with open(os.path.join(cache_dir, protocol.SIGNALS_FILE), newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for c in OUTCOME_COLUMNS:
            r[c] = float(r[c])
    return rows


def load_calendar(cache_dir=CACHE_DIR):
    with open(os.path.join(cache_dir, protocol.CALENDAR_FILE), encoding="utf-8") as f:
        return json.load(f)


def fetch_plan(keys, calendar=None):
    """Unique (ticker, prior_date) pairs to fetch, sorted. Enforces the lookahead rule: every fetch date
    must be STRICTLY earlier than the signal date (and, when a calendar is given, must be the prior session)."""
    pairs = set()
    for k in keys:
        if not k["prior_date"] < k["date"]:
            raise ValueError(f"lookahead: fetch date {k['prior_date']} is not before signal date {k['date']} "
                             f"({k['ticker']})")
        if calendar is not None and k["prior_date"] != prior_session(calendar, k["date"]):
            raise ValueError(f"{k['ticker']} {k['date']}: {k['prior_date']} is not the prior trading session")
        pairs.add((k["ticker"], k["prior_date"]))
    return sorted(pairs)


def _git(argus_root, *args):
    try:
        return subprocess.run(["git", "-C", argus_root, *args], capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--argus-root", default=DEFAULT_ARGUS_ROOT)
    ap.add_argument("--cache-dir", default=CACHE_DIR)
    args = ap.parse_args()
    tk = load_argus_toolkit(args.argus_root)
    rows, calendar, stats = build_signals(tk)
    plan = fetch_plan(rows, calendar)
    meta = {"stats": stats, "unique_fetch_pairs": len(plan),
            "argus": {"root": os.path.abspath(args.argus_root), "head": _git(args.argus_root, "rev-parse", "HEAD"),
                      "tracked_files_modified": len(_git(args.argus_root, "status", "--porcelain", "--untracked-files=no").splitlines())},
            "constants": {"rvol_threshold": tk.rvol_threshold, "target_r": tk.target_r, "hold_bars": tk.hold_bars,
                          "window_days": protocol.WINDOW_DAYS, "direction": protocol.DIRECTION}}
    write_exports(rows, calendar, meta, args.cache_dir)
    # Counts only: outcomes are deliberately not summarised here (no interim look, per the pre-registration).
    print(json.dumps({"stats": stats, "unique_fetch_pairs": len(plan), "calendar_days": len(calendar)}, indent=2))
    print(f"wrote {protocol.SIGNALS_FILE}, {protocol.KEYS_FILE}, {protocol.CALENDAR_FILE}, {protocol.META_FILE} "
          f"to {os.path.abspath(args.cache_dir)}")


if __name__ == "__main__":
    main()
