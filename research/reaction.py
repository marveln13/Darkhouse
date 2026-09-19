"""
Event study: when price first touches a level, does it hold or break?

Lookahead safety: ATR uses only bars BEFORE the touch; the touch bar itself
is excluded from the outcome window (its range trivially spans the level, so
it would make every touch look like a reaction). Outcome is measured on the
following bars of the same session only.

  support     price arrived from above; "hold" = rallies k*ATR off the level
              before falling k*ATR through it
  resistance  mirror image
  timeout     neither within `horizon` bars;  ambiguous = both in one bar
"""
import math
import statistics


def atr_before(bars, idx, n=14):
    lo = max(1, idx - n)
    trs = [max(bars[i]["high"] - bars[i]["low"],
               abs(bars[i]["high"] - bars[i - 1]["close"]),
               abs(bars[i]["low"] - bars[i - 1]["close"])) for i in range(lo, idx)]
    return sum(trs) / len(trs) if trs else None


def find_touch(bars, start, end, level):
    for i in range(start, end):
        if bars[i]["low"] <= level <= bars[i]["high"]:
            prev_close = bars[i - 1]["close"] if i > 0 else bars[i]["open"]
            if prev_close == level:
                return None
            return i, ("support" if prev_close > level else "resistance")
    return None


def classify(bars, touch_idx, end, level, side, atr, k=0.5, horizon=4):
    target = k * atr
    for j in range(touch_idx + 1, min(touch_idx + 1 + horizon, end)):
        b = bars[j]
        if side == "support":
            away, through = b["high"] - level >= target, level - b["low"] >= target
        else:
            away, through = level - b["low"] >= target, b["high"] - level >= target
        if away and through:
            return "ambiguous"
        if away:
            return "hold"
        if through:
            return "break"
    return "timeout"


def events_for_day(ticker, date, bars, day_range, labelled_levels, k=0.5, horizon=4):
    start, end = day_range
    events = []
    for lv in labelled_levels:
        touch = find_touch(bars, start, end, lv["price"])
        if touch is None:
            continue
        idx, side = touch
        atr = atr_before(bars, idx)
        if not atr:
            continue
        events.append({"ticker": ticker, "date": date, "group": lv["group"], "side": side,
                       "level": lv["price"], "outcome": classify(bars, idx, end, lv["price"], side, atr, k, horizon)})
    return events


def hold_rate(events):
    decided = [e for e in events if e["outcome"] in ("hold", "break")]
    return (sum(1 for e in decided if e["outcome"] == "hold") / len(decided)) if decided else None


def cluster_means(events, group):
    """Mean hold indicator per (ticker, date). Levels on the same ticker-day
    are not independent, so the unit of analysis is the ticker-day."""
    clusters = {}
    for e in events:
        if e["group"] == group and e["outcome"] in ("hold", "break"):
            clusters.setdefault((e["ticker"], e["date"]), []).append(1.0 if e["outcome"] == "hold" else 0.0)
    return [sum(v) / len(v) for v in clusters.values()]


def compare_groups(events, a="confluence", b="dp_only"):
    xs, ys = cluster_means(events, a), cluster_means(events, b)
    out = {"a": a, "b": b, "n_a": len(xs), "n_b": len(ys),
           "hold_a": statistics.mean(xs) if xs else None, "hold_b": statistics.mean(ys) if ys else None,
           "t": None, "p": None}
    if len(xs) >= 2 and len(ys) >= 2:
        se = math.sqrt(statistics.variance(xs) / len(xs) + statistics.variance(ys) / len(ys))
        if se > 0:
            out["t"] = (out["hold_a"] - out["hold_b"]) / se
            out["p"] = math.erfc(abs(out["t"]) / math.sqrt(2))  # normal approx; fine at large n
    return out
