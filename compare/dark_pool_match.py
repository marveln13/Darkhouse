"""
Does UW's dark-pool feed contain the prints ARGUS flagged as blocks?

ARGUS flags any FINRA-ADF (exchange 'D') print >= $200k notional, which the
real logs show is ~110-165 per minute in regular hours -- far too many to be
discrete block trades. The question this answers: what fraction of those does
UW's feed also list, and does UW carry big prints ARGUS never flagged? A low
match rate would mean UW's feed is a tighter (more block-like) filter than
ARGUS's, which is exactly what ARGUS lacks.

Matching is one-to-one on (ticker, size), price within `price_tol`, and time
within `time_tol_s`. ARGUS's `ts` is when it ingested the trade, not tape
time, so a small systematic lag is expected -- the median offset is reported.
"""
import statistics
from datetime import datetime

DEFAULT_MIN_NOTIONAL = 200_000


def _uw_dt(print_):
    return datetime.fromisoformat(print_.executed_at.replace("Z", "+00:00"))


def match_blocks(argus_blocks, uw_prints, time_tol_s=5.0, price_tol=0.02,
                 min_notional=DEFAULT_MIN_NOTIONAL):
    candidates = {}
    for p in uw_prints:
        if p.canceled or p.notional < min_notional:
            continue
        candidates.setdefault((p.ticker, p.size), []).append([_uw_dt(p), p, False])
    for lst in candidates.values():
        lst.sort(key=lambda c: c[0])

    matched, argus_only = [], []
    for a in sorted(argus_blocks, key=lambda b: b["dt"]):
        best, best_dt = None, None
        for c in candidates.get((a["ticker"], a["size"]), []):
            if c[2] or abs(c[1].price - a["price"]) > price_tol:
                continue
            delta = (a["dt"] - c[0]).total_seconds()
            if abs(delta) <= time_tol_s and (best is None or abs(delta) < abs(best_dt)):
                best, best_dt = c, delta
        if best is None:
            argus_only.append(a)
        else:
            best[2] = True
            matched.append((a, best[1], best_dt))

    uw_only = [c[1] for lst in candidates.values() for c in lst if not c[2]]
    n_argus, n_uw = len(argus_blocks), len(matched) + len(uw_only)
    return {
        "n_argus": n_argus,
        "n_uw": n_uw,
        "n_matched": len(matched),
        "argus_match_rate": len(matched) / n_argus if n_argus else None,
        "uw_match_rate": len(matched) / n_uw if n_uw else None,
        "median_lag_s": statistics.median(d for _, _, d in matched) if matched else None,
        "matched": matched,
        "argus_only": argus_only,
        "uw_only": uw_only,
    }
