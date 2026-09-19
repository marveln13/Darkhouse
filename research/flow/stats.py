"""
Inference exactly as registered in protocol.py: winsorized outcomes, day-level
cluster bootstrap, within-month score permutation, Spearman, half-split.
Rows are dicts with keys: date, bucket, score, and the outcome being tested.
"""
import numpy as np

from research.flow import protocol


def winsorize(values):
    v = np.asarray(values, dtype=float)
    lo, hi = np.quantile(v, protocol.WINSOR[0]), np.quantile(v, protocol.WINSOR[1])
    return np.clip(v, lo, hi)


def _usable(rows, key):
    return [r for r in rows if r.get(key) is not None]


def with_winsorized(rows, key):
    rows = _usable(rows, key)
    if not rows:
        return []
    w = winsorize([r[key] for r in rows])
    return [dict(r, _y=float(y)) for r, y in zip(rows, w)]


def bucket_table(rows, key):
    out = {}
    for b in ("low", "mid", "high"):
        raw = [r[key] for r in rows if r.get(key) is not None and r["bucket"] == b]
        w = with_winsorized([r for r in rows if r["bucket"] == b], key)
        out[b] = {"n": len(raw),
                  "mean_w": float(np.mean([r["_y"] for r in w])) if w else None,
                  "median": float(np.median(raw)) if raw else None,
                  "hit_rate": float(np.mean([x > 0 for x in raw])) if raw else None}
    return out


def _rank(x):
    x = np.asarray(x, dtype=float)
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x))
    ranks[order] = np.arange(len(x), dtype=float)
    for v in np.unique(x):                       # average ranks over ties
        m = x == v
        if m.sum() > 1:
            ranks[m] = ranks[m].mean()
    return ranks


def spearman(rows, key):
    w = with_winsorized(rows, key)
    if len(w) < 3:
        return None
    a, b = _rank([r["score"] for r in w]), _rank([r["_y"] for r in w])
    if a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def high_minus_low(rows, key):
    w = with_winsorized(rows, key)
    hi = [r["_y"] for r in w if r["bucket"] == "high"]
    lo = [r["_y"] for r in w if r["bucket"] == "low"]
    if not hi or not lo:
        return None
    return float(np.mean(hi) - np.mean(lo))


def cluster_bootstrap(rows, key, n=protocol.BOOTSTRAP_RESAMPLES, seed=protocol.STAT_SEED):
    """Resample DAYS (flow on one day is correlated across tickers) and recompute high - low."""
    w = with_winsorized(rows, key)
    days = sorted({r["date"] for r in w})
    if len(days) < 5:
        return None
    idx = {d: i for i, d in enumerate(days)}
    s = np.zeros((len(days), 2)); c = np.zeros((len(days), 2))
    for r in w:
        if r["bucket"] in ("high", "low"):
            j = 0 if r["bucket"] == "high" else 1
            s[idx[r["date"]], j] += r["_y"]; c[idx[r["date"]], j] += 1
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(n):
        pick = rng.integers(0, len(days), len(days))
        ss, cc = s[pick].sum(axis=0), c[pick].sum(axis=0)
        if cc[0] and cc[1]:
            diffs.append(ss[0] / cc[0] - ss[1] / cc[1])
    diffs = np.array(diffs)
    return {"lo": float(np.quantile(diffs, 0.025)), "hi": float(np.quantile(diffs, 0.975)),
            "p_two_sided": float(min(1.0, 2 * min((diffs <= 0).mean(), (diffs >= 0).mean())))}


def permutation_test(rows, key, n=protocol.PERMUTATIONS, seed=protocol.STAT_SEED):
    """Shuffle bucket labels WITHIN calendar month; how often is high - low at least as extreme?"""
    w = with_winsorized(rows, key)
    if not w:
        return None
    y = np.array([r["_y"] for r in w]); b = np.array([r["bucket"] for r in w])
    months = np.array([r["date"][:7] for r in w])
    obs = y[b == "high"].mean() - y[b == "low"].mean() if (b == "high").any() and (b == "low").any() else None
    if obs is None:
        return None
    groups = [np.where(months == m)[0] for m in np.unique(months)]
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(n):
        shuffled = b.copy()
        for g in groups:
            shuffled[g] = rng.permutation(b[g])
        if (shuffled == "high").any() and (shuffled == "low").any():
            hits += abs(y[shuffled == "high"].mean() - y[shuffled == "low"].mean()) >= abs(obs)
    return {"observed": float(obs), "p_two_sided": float((hits + 1) / (n + 1))}


def half_split(rows, key):
    dates = sorted({r["date"] for r in rows})
    if len(dates) < 4:
        return None
    cut = dates[len(dates) // 2]
    return {"first_half": high_minus_low([r for r in rows if r["date"] < cut], key),
            "second_half": high_minus_low([r for r in rows if r["date"] >= cut], key), "cut": cut}
