"""Inference exactly as registered: ISO-week cluster bootstrap, Holm, halves, verdict (PREREGISTRATION.md).
Rows are {"date", "group" ("A"/"B"), "y"}; the effect is mean(A) - mean(B), hypothesised > 0."""
from datetime import date as date_cls

import numpy as np

from research.argus_filter.stats import effect, half_split, holm, welch_t   # same definitions, reused
from research.regime_selector import protocol

__all__ = ["effect", "half_split", "holm", "welch_t", "iso_week", "week_bootstrap", "verdict"]


def iso_week(d):
    y, w, _ = date_cls.fromisoformat(d).isocalendar()
    return f"{y}-W{w:02d}"


def week_bootstrap(rows, n=protocol.BOOTSTRAP_RESAMPLES, seed=protocol.SEED):
    """Resample ISO weeks with replacement, recompute mean(A) - mean(B). p = 2 x min(share <= 0, share >= 0), capped
    at 1, over the resamples where both groups are present. None when there are too few weeks or a group is empty."""
    weeks = sorted({iso_week(r["date"]) for r in rows})
    if len(weeks) < 5 or effect(rows) is None:
        return None
    idx = {w: i for i, w in enumerate(weeks)}
    sums, counts = np.zeros((len(weeks), 2)), np.zeros((len(weeks), 2))
    for r in rows:
        j = 0 if r["group"] == "A" else 1
        sums[idx[iso_week(r["date"])], j] += r["y"]
        counts[idx[iso_week(r["date"])], j] += 1
    picks = np.random.default_rng(seed).integers(0, len(weeks), size=(n, len(weeks)))
    s, c = sums[picks].sum(axis=1), counts[picks].sum(axis=1)
    ok = (c[:, 0] > 0) & (c[:, 1] > 0)
    diffs = s[ok, 0] / c[ok, 0] - s[ok, 1] / c[ok, 1]
    lo, hi = np.quantile(diffs, [0.025, 0.975])
    p = min(1.0, 2 * min(float(np.mean(diffs <= 0)), float(np.mean(diffs >= 0))))
    return {"lo": float(lo), "hi": float(hi), "p": p, "weeks": len(weeks), "valid_resamples": int(ok.sum())}


def verdict(eff, p_holm, halves, placebo_effect, episodes):
    """Returns (status, failed). status: UNDERPOWERED / SUPPORTED / NOT SUPPORTED."""
    if min(episodes.values()) < protocol.MIN_EPISODES:
        return "UNDERPOWERED", ["episodes"]
    failed = []
    if p_holm is None or not p_holm < protocol.ALPHA:
        failed.append("holm_p")
    if eff is None or not eff > 0:
        failed.append("direction")
    if eff is None or not abs(eff) >= protocol.MIN_EFFECT_R:
        failed.append("min_effect")
    if halves is None or halves["first"] is None or halves["second"] is None \
            or not (halves["first"] > 0 and halves["second"] > 0):
        failed.append("halves")
    if placebo_effect is None or eff is None or not abs(placebo_effect) < protocol.PLACEBO_MAX_RATIO * abs(eff):
        failed.append("placebo")
    return ("NOT SUPPORTED" if failed else "SUPPORTED"), failed
