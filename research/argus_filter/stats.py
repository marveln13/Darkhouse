"""
Inference exactly as registered (PREREGISTRATION.md, "Statistics" and "Verdict rules").

Rows are dicts with `date` (ISO signal date), `group` ("A" or "B") and `y` (the signal's R). The effect is
always mean(A) - mean(B). The verdict never uses the naive t; sweeps cluster by day, so the bootstrap
resamples whole signal days.
"""
import numpy as np

from research.argus_filter import protocol


def _group(rows, g):
    return [r["y"] for r in rows if r["group"] == g]


def effect(rows):
    a, b = _group(rows, "A"), _group(rows, "B")
    return float(np.mean(a) - np.mean(b)) if a and b else None


def welch_t(rows):
    """Reported for context only -- never used for the verdict."""
    a, b = np.array(_group(rows, "A")), np.array(_group(rows, "B"))
    if len(a) < 2 or len(b) < 2:
        return None
    se = np.sqrt(a.var(ddof=1) / len(a) + b.var(ddof=1) / len(b))
    return float((a.mean() - b.mean()) / se) if se > 0 else None


def day_cluster_bootstrap(rows, n=protocol.BOOTSTRAP_RESAMPLES, seed=protocol.SEED):
    """Resample signal DAYS with replacement and recompute mean(A) - mean(B). Returns the 95% percentile CI and
    a two-sided p (twice the smaller tail of the resampled effects around 0, add-one so it is never exactly 0),
    or None when there are too few days or one group is empty."""
    days = sorted({r["date"] for r in rows})
    if len(days) < 5 or effect(rows) is None:
        return None
    idx = {d: i for i, d in enumerate(days)}
    sums, counts = np.zeros((len(days), 2)), np.zeros((len(days), 2))
    for r in rows:
        j = 0 if r["group"] == "A" else 1
        sums[idx[r["date"]], j] += r["y"]
        counts[idx[r["date"]], j] += 1
    picks = np.random.default_rng(seed).integers(0, len(days), size=(n, len(days)))
    s, c = sums[picks].sum(axis=1), counts[picks].sum(axis=1)
    ok = (c[:, 0] > 0) & (c[:, 1] > 0)
    diffs = s[ok, 0] / c[ok, 0] - s[ok, 1] / c[ok, 1]
    lo, hi = np.quantile(diffs, [0.025, 0.975])
    tail = min(int((diffs <= 0).sum()), int((diffs >= 0).sum()))
    return {"lo": float(lo), "hi": float(hi), "p": float(min(1.0, 2 * (tail + 1) / (len(diffs) + 1))),
            "valid_resamples": int(ok.sum())}


def holm(pvalues):
    """Holm step-down adjusted p-values for {name: p}. Order-independent; adjusted values are monotone."""
    m, out, running = len(pvalues), {}, 0.0
    for i, (name, p) in enumerate(sorted(pvalues.items(), key=lambda kv: kv[1])):
        running = max(running, min(1.0, (m - i) * p))
        out[name] = running
    return out


def half_split(rows):
    """Split the signals by date at the median signal date (first half strictly before it, second half on or
    after it, so a day is never divided) and report the effect in each half."""
    dates = sorted(r["date"] for r in rows)
    if len(dates) < 4:
        return None
    cut = dates[len(dates) // 2]
    first, second = [r for r in rows if r["date"] < cut], [r for r in rows if r["date"] >= cut]
    return {"cut": cut, "first": effect(first), "second": effect(second), "n_first": len(first), "n_second": len(second)}


def hypothesis_verdict(direction, eff, p_holm, first, second, placebo_effect, placebo_required=True):
    """SUPPORTED only if ALL hold: Holm-adjusted p < alpha; the effect and BOTH halves point the hypothesised way
    (which also makes the halves agree in sign); the placebo effect is smaller in magnitude than half the real
    effect (only where a placebo is registered -- see protocol.PLACEBO_REQUIRED); |effect| >= MIN_EFFECT_R.
    Returns (supported, [names of the failed conditions])."""
    failed = []
    if p_holm is None or not p_holm < protocol.ALPHA:
        failed.append("holm_p")
    if eff is None or not eff * direction > 0:
        failed.append("direction")
    if first is None or second is None or not (first * direction > 0 and second * direction > 0):
        failed.append("halves")
    if placebo_required and (placebo_effect is None or eff is None
                             or not abs(placebo_effect) < protocol.PLACEBO_MAX_RATIO * abs(eff)):
        failed.append("placebo")
    if eff is None or not abs(eff) >= protocol.MIN_EFFECT_R:
        failed.append("min_effect")
    return (not failed), failed


def study_status(n_complete):
    """The minimum-sample rule: fewer than MIN_SIGNALS complete signals means no verdict at all."""
    return "UNDERPOWERED" if n_complete < protocol.MIN_SIGNALS else "EVALUABLE"
