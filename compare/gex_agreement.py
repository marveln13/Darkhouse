"""
Do ARGUS's ThetaData-derived SPY GEX regime and UW's net gamma agree on sign?

ARGUS's cache holds ~120 real days; each date's value comes from the prior
day's end-of-day Greeks/OI, so it is paired with UW's gamma for `prior_day`.
Caveats stated up front, not buried:
  - Scope differs: ARGUS sums 0-7 DTE within +/-15% of spot; UW's total is
    unspecified. Only the SIGN (regime) is compared, not magnitudes.
  - UW's sign convention for put gamma is undocumented, so two are tried:
    "signed" (call + put, if puts are already negative) and "magnitude"
    (call - |put|, if puts come back as positive numbers). The convention
    that agrees is itself the finding; picking the better of two after
    looking is a one-bit choice, but it is reported, not hidden.
"""
import math
import statistics

CONVENTIONS = ("signed", "magnitude")


def uw_net_gamma(row, convention):
    if convention == "signed":
        return row.call_gamma + row.put_gamma
    return row.call_gamma - abs(row.put_gamma)


def _pearson(xs, ys):
    if len(xs) < 3 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    return statistics.correlation(xs, ys)


def compare_gex(argus_cache, uw_history):
    uw_by_date = {row.date: row for row in uw_history}
    results = {}
    for convention in CONVENTIONS:
        pairs = []
        for _, entry in sorted(argus_cache.items()):
            row = uw_by_date.get(entry.get("prior_day"))
            if row is None or not entry.get("gex"):
                continue
            pairs.append((entry["prior_day"], entry["gex"], uw_net_gamma(row, convention)))

        n = len(pairs)
        agree = sum(1 for _, a, u in pairs if (a < 0) == (u < 0))
        uw_positive_share = sum(1 for _, _, u in pairs if u > 0) / n if n else None
        rate = agree / n if n else None
        results[convention] = {
            "n": n,
            "sign_agreement": rate,
            "z_vs_coinflip": (rate - 0.5) / math.sqrt(0.25 / n) if n else None,
            "pearson": _pearson([a for _, a, _ in pairs], [u for _, _, u in pairs]),
            "uw_positive_share": uw_positive_share,
            "uw_sign_suspect": uw_positive_share is not None and (uw_positive_share > 0.95 or uw_positive_share < 0.05),
            "disagreement_dates": [d for d, a, u in pairs if (a < 0) != (u < 0)],
        }
    return results
