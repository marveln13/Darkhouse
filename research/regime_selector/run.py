"""
The regime-selector study, run exactly as pre-registered (research/regime_selector/PREREGISTRATION.md + Addendum 1).

    python -m research.regime_selector.run --structure     # regime counts, episodes, signals per regime -- no R shown
    python -m research.regime_selector.run                 # the ONE registered run -> verdicts, RESULTS.md

Day D's regime = the sign of UW's SPY net gamma (call + put) on the prior session. H1: M30i PUTS (a fade) does better on
POS days. H2: the live ORB UP (a breakout) does better on NEG days. The ARGUS populations are imported from the ARGUS checkout,
not re-implemented. UW responses, Alpaca pre-market ranges and VIX1D rows are cached under the gitignored .cache/.
"""
import argparse
import bisect
import json
import os
import sys
from collections import Counter, namedtuple
from datetime import date as date_cls, datetime, timezone

from dotenv import load_dotenv

from research.regime_selector import protocol, stats
from research.regime_selector.regime import Regime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_ARGUS_ROOT = os.path.join(REPO_ROOT, "..", "ai-trading-desk-2")
CACHE_DIR = os.path.join(REPO_ROOT, ".cache", protocol.CACHE_SUBDIR)
UW_CACHE_DIR = os.path.join(REPO_ROOT, ".cache", "uw")
RESULTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RESULTS.md")

Toolkit = namedtuple("Toolkit", "universe m30i_puts_signals load_m15 parse_ts detect_gap_and_go tag_confluence "
                                "simulate_trade build_vix1d_buckets constants")


def load_argus_toolkit(argus_root):
    """Import the real ARGUS functions. ARGUS goes AFTER this repo on sys.path so this repo's own packages win."""
    root = os.path.abspath(argus_root)
    if root not in sys.path:
        sys.path.insert(1, root)
    from backtest.test_m30_bidirectional_direction_rule import UNIVERSE
    from backtest.test_orb import load_cached, parse_ts
    from backtest.test_orb_premarket_confluence_gap_and_go_only import MIN_BREAKOUT_BAR_INDEX, detect_gap_and_go_signals
    from backtest.test_orb_premarket_confluence_real import tag_confluence
    from backtest.test_vix1d_regime_confluence import (M30_PUTS_HOLD_BARS, M30_PUTS_TARGET_R, build_regime_buckets,
                                                       m30i_puts_signals)
    from backtest.trade_simulator import simulate_trade
    from config import GAP_AND_GO_CALLS_THRESHOLD_PCT
    from detection.orb_engine import PREMARKET_CONFLUENCE_ENABLED
    return Toolkit(tuple(UNIVERSE), m30i_puts_signals, load_cached, parse_ts, detect_gap_and_go_signals, tag_confluence,
                   simulate_trade, build_regime_buckets,
                   {"universe_size": len(UNIVERSE), "m30_target_r": M30_PUTS_TARGET_R, "m30_hold": M30_PUTS_HOLD_BARS,
                    "orb_gap_pct": GAP_AND_GO_CALLS_THRESHOLD_PCT, "orb_min_bar": MIN_BREAKOUT_BAR_INDEX,
                    "premarket_gate": PREMARKET_CONFLUENCE_ENABLED})


def check_pinned(tk):
    want = {"universe_size": protocol.UNIVERSE_SIZE, "m30_target_r": protocol.PINNED_M30_TARGET_R,
            "m30_hold": protocol.PINNED_M30_HOLD_BARS, "orb_gap_pct": protocol.PINNED_ORB_GAP_PCT,
            "orb_min_bar": protocol.PINNED_ORB_MIN_BREAKOUT_BAR, "premarket_gate": True}
    drift = {k: (tk.constants.get(k), v) for k, v in want.items() if tk.constants.get(k) != v}
    if drift:
        raise RuntimeError(f"ARGUS differs from the pre-registration (got, pinned): {drift}")


# ---------------------------------------------------------------- populations

def orb_up_pairs(tk, premarket_by_date):
    """The live ORB UP (Addendum 1): gap-and-go signals, the live pre-market-high gate, 2.5R, 26 M15 bars.
    premarket_by_date is {date: {ticker: range}} with date objects, as ARGUS's tag_confluence expects.
    Returns ([(day_iso, r)], Counter of exclusions)."""
    pairs, stats_ = [], Counter()
    for ticker in tk.universe:
        bars = tk.load_m15(ticker)
        if not bars:
            stats_["no_m15_cache"] += 1
            continue
        signals = tk.detect_gap_and_go(ticker, bars)
        stats_["gap_and_go"] += len(signals)
        tagged = tk.tag_confluence(signals, {ticker: bars}, premarket_by_date)
        stats_["no_premarket"] += len(signals) - len(tagged)
        ts_list = [tk.parse_ts(b["timestamp"]) for b in bars]
        for s in tagged:
            if not s["_confluence"]:
                stats_["premarket_gate_failed"] += 1
                continue
            ts = tk.parse_ts(s["timestamp"])
            idx = bisect.bisect_right(ts_list, ts) - 1
            if idx < 0:
                stats_["no_bar"] += 1
                continue
            r = tk.simulate_trade(bars, ts_list, idx, "up", s["entry_price"], s["stop_price"],
                                  protocol.ORB_TARGET_R, max_bars_forward=protocol.ORB_MAX_BARS)
            if r is None:
                stats_["no_outcome"] += 1
                continue
            pairs.append((ts.date().isoformat(), r))
    return pairs, stats_


def gap_and_go_dates(tk):
    """Signal dates needing pre-market ranges (before the gate), as ISO strings."""
    out = set()
    for ticker in tk.universe:
        bars = tk.load_m15(ticker)
        if bars:
            out.update(tk.parse_ts(s["timestamp"]).date().isoformat() for s in tk.detect_gap_and_go(ticker, bars))
    return sorted(out)


# ---------------------------------------------------------------- cached external data

def _load_json(name, default):
    path = os.path.join(CACHE_DIR, name)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def _save_json(name, data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = os.path.join(CACHE_DIR, name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, os.path.join(CACHE_DIR, name))


def premarket_ranges(tk, dates, fetch=True):
    """{date: {ticker: range}} for the given ISO dates, from the local cache, fetching missing dates from Alpaca."""
    cache = _load_json(protocol.PREMARKET_FILE, {})
    missing = [d for d in dates if d not in cache]
    if missing and fetch:
        from feed.alpaca_feed import AlpacaDataFeed
        feed = AlpacaDataFeed()
        if not feed.live:
            raise RuntimeError("Alpaca feed not live -- cannot fetch pre-market ranges")
        for k, d in enumerate(missing, 1):
            cache[d] = feed.get_premarket_ranges(list(tk.universe), target_date=date_cls.fromisoformat(d)) or {}
            if k % 20 == 0:
                _save_json(protocol.PREMARKET_FILE, cache)
                print(f"  pre-market ranges: {k}/{len(missing)} dates fetched")
        _save_json(protocol.PREMARKET_FILE, cache)
    return {date_cls.fromisoformat(d): v for d, v in cache.items() if v}


def uw_regime(fetch=True):
    from research.caching_client import CachingClient
    from src import gex
    from src.uw_client import UnusualWhalesClient
    client = CachingClient(UnusualWhalesClient() if fetch else None, UW_CACHE_DIR)
    return Regime(gex.greek_exposure_history(client, protocol.UW_TICKER, timeframe=protocol.UW_TIMEFRAME))


def vix1d_buckets(tk):
    """VIX1D buckets (the VIX1D study's own definition) for the secondary, or None when ThetaData is unavailable."""
    rows = _load_json(protocol.VIX1D_FILE, None)
    if rows is None:
        try:
            from feed.thetadata_feed import ThetaDataFeed
            feed = ThetaDataFeed()
            if not feed.live:
                return None
            rows = feed.fetch_index_history_chunked("VIX1D", date_cls(2024, 1, 2), date_cls.today())
            _save_json(protocol.VIX1D_FILE, rows)
        except Exception as e:                       # the secondary is optional; the primary never depends on it
            print(f"  VIX1D unavailable ({type(e).__name__}: {e}) -- secondary skipped")
            return None
    return tk.build_vix1d_buckets(rows)


# ---------------------------------------------------------------- analysis

def label_pairs(pairs, regime):
    """[(day, r)] -> rows with the regime and placebo label; days with no prior UW session are dropped (counted)."""
    rows, dropped = [], 0
    for day, r in pairs:
        lab = regime.for_day(day)
        if lab is None:
            dropped += 1
            continue
        rows.append({"date": day, "r": r, "regime": lab, "placebo": regime.placebo_for_day(day)})
    return rows, dropped


def grouped(rows, a, b, key="regime"):
    return [{"date": r["date"], "group": "A" if r[key] == a else "B", "y": r["r"]} for r in rows if r[key] in (a, b)]


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def analyse(setups, regime, vix=None):
    """setups: {"m30i_puts": rows, "orb_up": rows} from label_pairs. Returns the full result dict."""
    hyps = {}
    for name, h in protocol.HYPOTHESES.items():
        rows = setups[h["setup"]]
        real = grouped(rows, h["A"], h["B"])
        placebo = grouped([r for r in rows if r["placebo"] is not None], h["A"], h["B"], key="placebo")
        first, last = min(r["date"] for r in rows), max(r["date"] for r in rows)
        hyps[name] = {"label": h["label"], "n": len(real), "window": (first, last),
                      "n_a": sum(r["group"] == "A" for r in real), "n_b": sum(r["group"] == "B" for r in real),
                      "mean_a": mean(r["y"] for r in real if r["group"] == "A"),
                      "mean_b": mean(r["y"] for r in real if r["group"] == "B"),
                      "effect": stats.effect(real), "naive_t": stats.welch_t(real),
                      "bootstrap": stats.week_bootstrap(real), "halves": stats.half_split(real),
                      "placebo_effect": stats.effect(placebo), "episodes": regime.episodes(first, last)}
    pvals = {k: h["bootstrap"]["p"] for k, h in hyps.items() if h["bootstrap"]}
    adjusted = stats.holm(pvals) if len(pvals) == len(hyps) else {}
    for k, h in hyps.items():
        h["p_holm"] = adjusted.get(k)
        h["status"], h["failed"] = stats.verdict(h["effect"], h["p_holm"], h["halves"], h["placebo_effect"], h["episodes"])
    return {"hypotheses": hyps, "secondary": secondary(setups, vix)}


def secondary(setups, vix):
    m30, orb = setups["m30i_puts"], setups["orb_up"]
    lo, hi = min(r["date"] for r in orb), max(r["date"] for r in orb)          # the ORB window bounds the overlap
    m30w = [r for r in m30 if lo <= r["date"] <= hi]
    days = sorted({r["date"] for r in m30w + orb})
    both = sum(r["r"] for r in m30w) + sum(r["r"] for r in orb)
    sel = [r for r in m30w if r["regime"] == protocol.POS] + [r for r in orb if r["regime"] == protocol.NEG]
    out = {"overlap": (lo, hi), "days": len(days),
           "both_always": {"total_r": both, "trades": len(m30w) + len(orb)},
           "selector": {"total_r": sum(r["r"] for r in sel), "trades": len(sel)},
           "base": {k: {"n": len(v), "mean_r": mean(r["r"] for r in v),
                        "pos_share": mean(1.0 if r["regime"] == protocol.POS else 0.0 for r in v)}
                    for k, v in setups.items()}}
    if vix:
        labelled = {r["date"]: r["regime"] for v in setups.values() for r in v}
        common = [d for d in labelled if d in vix]
        out["vix1d_agreement"] = mean(1.0 if (labelled[d] == protocol.NEG) == (vix[d] == "HIGH") else 0.0 for d in common)
        out["within_vix1d"] = {}
        for name, h in protocol.HYPOTHESES.items():
            for bucket in ("HIGH", "LOW"):
                rows = [r for r in setups[h["setup"]] if vix.get(r["date"]) == bucket]
                out["within_vix1d"][f"{name} {bucket}"] = {"n": len(rows), "effect": stats.effect(grouped(rows, h["A"], h["B"]))}
    return out


def _f(x, spec="+.3f"):
    return "n/a" if x is None else format(x, spec)


def render(res, meta):
    lines = [f"sanity gate: M30i PUTS all-days mean {_f(meta['sanity_mean'])}R "
             f"(registered {protocol.SANITY_M30_MEAN_R:+.3f} +/- {protocol.SANITY_TOLERANCE_R}) -> OK",
             f"excluded: {meta['excluded']}"]
    for k, h in res["hypotheses"].items():
        b, half = h["bootstrap"] or {}, h["halves"] or {}
        lines += ["", h["label"],
                  f"  window {h['window'][0]}..{h['window'][1]} | regime episodes {h['episodes']}",
                  f"  n={h['n']:,} (A {h['n_a']:,}, B {h['n_b']:,}) | mean R: A {_f(h['mean_a'])}  B {_f(h['mean_b'])}",
                  f"  effect {_f(h['effect'])}R | 95% CI (ISO-week bootstrap, {b.get('weeks')} weeks) "
                  f"[{_f(b.get('lo'))}, {_f(b.get('hi'))}] | p {_f(b.get('p'), '.4f')} | Holm p {_f(h['p_holm'], '.4f')} "
                  f"| naive t {_f(h['naive_t'], '.2f')} (not used)",
                  f"  halves (cut {half.get('cut')}): first {_f(half.get('first'))}, second {_f(half.get('second'))}",
                  f"  placebo (regime shifted {protocol.PLACEBO_SHIFT_SESSIONS} sessions) {_f(h['placebo_effect'])}R "
                  f"(must be < {protocol.PLACEBO_MAX_RATIO} x |real|)",
                  f"  -> {h['status']}" + (f" (failed: {', '.join(h['failed'])})" if h["failed"] else "")]
    s = res["secondary"]
    lines += ["", "SECONDARY (no verdict)",
              f"  overlap {s['overlap'][0]}..{s['overlap'][1]} ({s['days']} signal days): both setups always "
              f"{s['both_always']['total_r']:+.1f}R over {s['both_always']['trades']:,} trades | selector "
              f"{s['selector']['total_r']:+.1f}R over {s['selector']['trades']:,} trades"]
    for k, v in s["base"].items():
        lines.append(f"  {k}: n={v['n']:,}, mean {_f(v['mean_r'])}R, POS-day share {_f(v['pos_share'] and 100 * v['pos_share'], '.1f')}%")
    if "vix1d_agreement" in s:
        lines.append(f"  UW NEG vs VIX1D HIGH agreement: {_f(s['vix1d_agreement'] and 100 * s['vix1d_agreement'], '.1f')}% of days")
        lines += [f"  within VIX1D {k}: effect {_f(v['effect'])} (n={v['n']:,})" for k, v in s["within_vix1d"].items()]
    else:
        lines.append("  VIX1D secondary: not available (ThetaData offline)")
    lines += ["", "VERDICT: " + ", ".join(f"{k} {h['status']}" for k, h in res["hypotheses"].items())]
    return "\n".join(lines)


# ---------------------------------------------------------------- modes

def build(tk, fetch=True):
    check_pinned(tk)
    regime = uw_regime(fetch)
    m30_pairs = tk.m30i_puts_signals(list(tk.universe))
    pm = premarket_ranges(tk, gap_and_go_dates(tk), fetch=fetch)
    orb_pairs, orb_stats = orb_up_pairs(tk, pm)
    m30_rows, m30_dropped = label_pairs(m30_pairs, regime)
    orb_rows, orb_dropped = label_pairs(orb_pairs, regime)
    excluded = {"m30i_no_prior_uw_session": m30_dropped, "orb_no_prior_uw_session": orb_dropped, **dict(orb_stats)}
    return regime, {"m30i_puts": m30_rows, "orb_up": orb_rows}, excluded


def structure(tk):
    regime, setups, excluded = build(tk)
    out = {"uw_sessions": len(regime.dates), "uw_range": (regime.dates[0], regime.dates[-1]),
           "uw_pos_share": round(regime.labels.count(protocol.POS) / len(regime.labels), 3), "excluded": excluded}
    for k, rows in setups.items():
        first, last = min(r["date"] for r in rows), max(r["date"] for r in rows)
        out[k] = {"signals": len(rows), "window": (first, last), "by_regime": dict(Counter(r["regime"] for r in rows)),
                  "signal_days": len({r["date"] for r in rows}), "episodes": regime.episodes(first, last)}
    print(json.dumps(out, indent=2))                   # counts only -- no R


def run(tk, allow_rerun=False):
    marker_path = os.path.join(CACHE_DIR, protocol.MARKER_FILE)
    marker = None
    if os.path.exists(marker_path):
        if not allow_rerun:
            raise SystemExit(f"{marker_path} exists: the registered analysis has already run once. "
                             f"Pass --allow-rerun to run again (logged in the marker).")
        with open(marker_path, encoding="utf-8") as f:
            marker = json.load(f)
    regime, setups, excluded = build(tk)
    sanity = mean(r["r"] for r in setups["m30i_puts"])
    if sanity is None or abs(sanity - protocol.SANITY_M30_MEAN_R) > protocol.SANITY_TOLERANCE_R:
        raise SystemExit(f"SANITY GATE FAILED: M30i PUTS all-days mean {sanity}; nothing else computed, no marker written.")
    res = analyse(setups, regime, vix1d_buckets(tk))
    text = render(res, {"sanity_mean": sanity, "excluded": excluded})
    print(text)
    now = datetime.now(timezone.utc).isoformat()
    verdicts = {k: h["status"] for k, h in res["hypotheses"].items()}
    if marker is None:
        marker = {"first_run": now, "reruns": [], "verdict": verdicts}
    else:
        marker["reruns"].append({"at": now, "verdict": verdicts})
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(marker_path, "w", encoding="utf-8") as f:
        json.dump(marker, f, indent=2)
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:              # aggregates only -- safe to commit
        f.write("# Regime-selector study results\n\nGenerated by `python -m research.regime_selector.run` "
                f"({now}) under PREREGISTRATION.md + Addendum 1. Aggregate statistics only.\n\n```\n{text}\n```\n")
    print(f"\nwrote {RESULTS_FILE}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--structure", action="store_true", help="counts only; no outcome is shown")
    ap.add_argument("--allow-rerun", action="store_true")
    ap.add_argument("--argus-root", default=DEFAULT_ARGUS_ROOT)
    args = ap.parse_args()
    tk = load_argus_toolkit(args.argus_root)
    structure(tk) if args.structure else run(tk, args.allow_rerun)


if __name__ == "__main__":
    load_dotenv()
    main()
