"""
Does UW's options-flow direction agree with ARGUS's own flow log, per
ticker per day?

ARGUS side: sum of `net_aggressive_dollar_delta` over the day's 5-minute
snapshots (all trades, delta-weighted, aggressor-classified against real
NBBO). UW side: bullish minus bearish premium over that day's flow alerts
(rule-filtered, premium-weighted). These are genuinely different measures,
so only the sign per (date, ticker) is compared; disagreement is expected
to be real, not just noise, and is the interesting output.
"""
import math
import statistics

from src import analysis

from .argus_logs import et_date, is_regular_hours


def argus_daily_flow(snapshots):
    daily = {}
    for s in snapshots:
        if not is_regular_hours(s["dt"]):
            continue
        key = (et_date(s["dt"]), s["ticker"])
        daily[key] = daily.get(key, 0.0) + (s.get("net_aggressive_dollar_delta") or 0.0)
    return daily


def uw_daily_flow(alerts_by_key):
    """alerts_by_key: {(date, ticker): [FlowAlert]} -> signed premium tilt."""
    out = {}
    for key, alerts in alerts_by_key.items():
        bias = analysis.flow_bias(alerts)
        out[key] = bias["bullish_premium"] - bias["bearish_premium"]
    return out


def _signed_log(x):
    return math.copysign(math.log1p(abs(x)), x)


def compare_flow(argus_daily, uw_daily):
    keys = [k for k in argus_daily if k in uw_daily and argus_daily[k] != 0 and uw_daily[k] != 0]
    n = len(keys)
    agree = sum(1 for k in keys if (argus_daily[k] > 0) == (uw_daily[k] > 0))
    rate = agree / n if n else None
    xs = [_signed_log(argus_daily[k]) for k in keys]
    ys = [_signed_log(uw_daily[k]) for k in keys]
    pearson = statistics.correlation(xs, ys) if n >= 3 and len(set(xs)) > 1 and len(set(ys)) > 1 else None
    return {
        "n": n,
        "sign_agreement": rate,
        "z_vs_coinflip": (rate - 0.5) / math.sqrt(0.25 / n) if n else None,
        "pearson_signed_log": pearson,
        "disagreements": sorted(k for k in keys if (argus_daily[k] > 0) != (uw_daily[k] > 0)),
    }
