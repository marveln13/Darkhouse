import csv
import inspect
import os
from datetime import datetime

import pytest

from research.argus_filter import fetch, protocol, signals
from research.argus_filter.signals import Toolkit

# Weekdays in Aug 2026 with two M30 bars each (13:30 and 14:00 UTC = 9:30 / 10:00 ET, EDT).
DAYS = ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10"]


def ts(day, hhmm="13:30"):
    return f"{day}T{hhmm}:00.000+0000"


def bars_for(days):
    return [{"timestamp": ts(d, h), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000}
            for d in days for h in ("13:30", "14:00")]


def sig(ticker, day, idx, entry, stop, rvol, hhmm="13:30"):
    return {"ticker": ticker, "direction": "up", "entry_idx": idx, "timestamp": ts(day, hhmm),
            "entry_price": entry, "stop_price": stop, "rvol_20": rvol}


def dedup_earliest(rows):                      # same rule as ARGUS's: one per (ticker, day), earliest timestamp
    best = {}
    for s in rows:
        k = (s["ticker"], s["timestamp"][:10])
        if k not in best or s["timestamp"] < best[k]["timestamp"]:
            best[k] = s
    return list(best.values())


def make_toolkit(found, days=DAYS, sim_calls=None, **over):
    def find(ticker, bars, atrs):
        return list(found.get(ticker, []))

    def simulate(bars, ts_list, idx, direction, entry, stop, target_r, max_bars_forward):
        if sim_calls is not None:
            sim_calls.append((idx, direction, entry, stop, target_r, max_bars_forward))
        return -1.0

    kw = dict(watchlist=list(found), load_m30=lambda t: bars_for(days), atr_series=lambda b: [1.0] * len(b),
              find_signals=find, dedup_earliest=dedup_earliest, simulate_trade=simulate,
              parse_ts=datetime.fromisoformat, rvol_threshold=1.01, target_r=3.0, hold_bars=13)
    kw.update(over)
    return Toolkit(**kw)


# ---- D-1 rule ----

def test_prior_session_skips_weekends_and_holidays():
    cal = ["2026-09-03", "2026-09-04", "2026-09-08", "2026-09-09"]        # 09-07 is Labor Day
    assert signals.prior_session(cal, "2026-09-08") == "2026-09-04"
    assert signals.prior_session(cal, "2026-09-09") == "2026-09-08"
    assert signals.prior_session(cal, "2026-09-07") == "2026-09-04"       # a non-session date still resolves backwards
    assert signals.prior_session(cal, "2026-09-03") is None               # nothing earlier in the calendar


def test_fetch_plan_is_unique_sorted_and_enforces_the_lookahead_rule():
    keys = [{"ticker": "B", "date": "2026-09-09", "prior_date": "2026-09-08"},
            {"ticker": "A", "date": "2026-09-09", "prior_date": "2026-09-08"},
            {"ticker": "A", "date": "2026-09-09", "prior_date": "2026-09-08"}]      # duplicate pair
    assert signals.fetch_plan(keys) == [("A", "2026-09-08"), ("B", "2026-09-08")]

    with pytest.raises(ValueError, match="lookahead"):                     # same-day data is lookahead
        signals.fetch_plan([{"ticker": "A", "date": "2026-09-09", "prior_date": "2026-09-09"}])
    with pytest.raises(ValueError, match="lookahead"):                     # later data is worse
        signals.fetch_plan([{"ticker": "A", "date": "2026-09-09", "prior_date": "2026-09-10"}])


def test_fetch_plan_with_a_calendar_requires_the_actual_prior_session():
    cal = ["2026-09-03", "2026-09-04", "2026-09-08"]
    ok = {"ticker": "A", "date": "2026-09-08", "prior_date": "2026-09-04"}
    assert signals.fetch_plan([ok], cal) == [("A", "2026-09-04")]
    stale = dict(ok, prior_date="2026-09-03")                              # earlier than D, but not D-1
    with pytest.raises(ValueError, match="prior trading session"):
        signals.fetch_plan([stale], cal)


# ---- the export pipeline (ARGUS functions injected) ----

def test_build_signals_filters_loud_dedups_mirrors_and_windows():
    calls = []
    found = {"AAA": [
        sig("AAA", "2026-08-05", 5, entry=100.0, stop=98.0, rvol=1.5, hhmm="14:00"),   # loud, later same day
        sig("AAA", "2026-08-05", 4, entry=101.0, stop=99.0, rvol=1.2, hhmm="13:30"),   # loud, EARLIER same day -> kept
        sig("AAA", "2026-08-06", 6, entry=100.0, stop=98.0, rvol=0.9),                 # not loud -> dropped
        sig("AAA", "2026-08-07", 8, entry=100.0, stop=100.0, rvol=2.0),                # zero risk -> skipped
        sig("AAA", "2026-08-10", 10, entry=100.0, stop=101.0, rvol=2.0),               # gapped THROUGH the stop: |risk|=1
    ]}
    rows, calendar, stats = signals.build_signals(make_toolkit(found, sim_calls=calls))

    assert calendar == DAYS
    assert [(r["date"], r["prior_date"]) for r in rows] == [("2026-08-05", "2026-08-04"), ("2026-08-10", "2026-08-07")]
    first, gap = rows
    assert (first["entry"], first["risk"], first["stop"], first["target"]) == (101.0, 2.0, 103.0, 95.0)   # mirrored put
    assert (gap["entry"], gap["risk"], gap["stop"], gap["target"]) == (100.0, 1.0, 101.0, 97.0)          # abs(risk)
    assert calls == [(4, "down", 101.0, 103.0, 3.0, 13), (10, "down", 100.0, 101.0, 3.0, 13)]
    assert stats["raw_signals"] == 5 and stats["loud_signals"] == 4 and stats["deduped_signals"] == 3
    assert stats["zero_risk"] == 1 and stats["exported"] == 2


def test_build_signals_drops_signals_outside_the_365_day_window():
    days = ["2025-07-01", "2025-08-01", "2025-08-04", "2026-08-03", "2026-08-04"]   # start = 2026-08-04 - 365d = 2025-08-04
    found = {"AAA": [sig("AAA", d, 5, 100.0, 99.0, 2.0) for d in days]}
    rows, _, stats = signals.build_signals(make_toolkit(found, days=days))
    assert [r["date"] for r in rows] == ["2025-08-04", "2026-08-03", "2026-08-04"]   # the start date itself is inside
    assert stats["before_window"] == 2 and stats["window_start"] == "2025-08-04"


def test_the_loud_threshold_is_inclusive():
    found = {"AAA": [sig("AAA", "2026-08-04", 4, 100.0, 99.0, 1.01), sig("AAA", "2026-08-05", 6, 100.0, 99.0, 1.0099)]}
    rows, _, _ = signals.build_signals(make_toolkit(found))
    assert [r["date"] for r in rows] == ["2026-08-04"]                       # rvol_20 >= 1.01 keeps; just below drops


def test_build_signals_uses_the_et_session_date_and_a_missing_cache_is_counted():
    found = {"AAA": [sig("AAA", "2026-08-05", 4, 100.0, 99.0, 2.0)], "NOCACHE": []}
    tk = make_toolkit(found, load_m30=lambda t: [] if t == "NOCACHE" else bars_for(DAYS))
    rows, _, stats = signals.build_signals(tk)
    assert len(rows) == 1 and stats["tickers_without_cache"] == 1 and stats["tickers_used"] == 1


def test_check_pinned_refuses_a_drifted_arguss_constants():
    signals.check_pinned(make_toolkit({}))                                   # pinned values: fine
    for field, bad in (("rvol_threshold", 1.5), ("target_r", 2.0), ("hold_bars", 26)):
        with pytest.raises(RuntimeError, match="pre-registration"):
            signals.check_pinned(make_toolkit({}, **{field: bad}))


# ---- the fetch cannot see outcomes ----

def test_keys_file_has_no_outcomes_and_signals_file_does(tmp_path):
    found = {"AAA": [sig("AAA", "2026-08-05", 4, 100.0, 98.0, 2.0)]}
    rows, calendar, stats = signals.build_signals(make_toolkit(found))
    signals.write_exports(rows, calendar, {"stats": stats}, str(tmp_path))

    with open(tmp_path / protocol.KEYS_FILE, newline="") as f:
        assert next(csv.reader(f)) == list(signals.KEY_COLUMNS)
    keys = signals.load_keys(str(tmp_path))
    assert set(keys[0]) == set(signals.KEY_COLUMNS) and "r" not in keys[0]
    full = signals.load_signals(str(tmp_path))
    assert full[0]["r"] == -1.0 and full[0]["entry"] == 100.0 and full[0]["target"] == 94.0


def test_fetch_module_never_touches_the_outcome_loader_or_file():
    source = inspect.getsource(fetch)
    for banned in ("load_signals", "SIGNALS_FILE", "signals.csv", "OUTCOME_COLUMNS"):
        assert banned not in source
    assert not hasattr(fetch, "load_signals")
    assert os.path.basename(protocol.KEYS_FILE) != os.path.basename(protocol.SIGNALS_FILE)
