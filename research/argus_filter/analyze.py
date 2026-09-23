"""
Step 3 of the implementation checklist: the analysis, implementing PREREGISTRATION.md exactly.

    python -m research.argus_filter.analyze --coverage     # how many signals have complete UW data (no outcomes read)
    python -m research.argus_filter.analyze                # the ONE analysis run, after the fetch has stopped

The analysis runs once. A marker file records the run; a second run is refused unless --allow-rerun is given
(and the marker then lists every rerun), because the registration forbids interim looks at outcomes. `--coverage`
never opens signals.csv, so it is safe to use while the fetch is still going.

Per signal on session D: the levels are D-1's (dark-pool top-5 + call_wall/put_wall/gamma_flip/gamma_magnet) read
from the cached UW responses. A signal with missing D-1 dark-pool OR GEX data is excluded and counted.
  H1 obstacle:  >= 1 level with target <= level < entry  ->  LOWER mean R than signals with none
  H2 regime:    entry below D-1 gamma_flip               ->  HIGHER mean R than signals above it
"""
import argparse
import json
import os
from collections import Counter
from datetime import datetime, timezone

from dotenv import load_dotenv

from research.argus_filter import levels, protocol, stats
from research.argus_filter.signals import CACHE_DIR, REPO_ROOT, load_keys, load_signals
from research.caching_client import CachingClient

UW_CACHE_DIR = os.path.join(REPO_ROOT, ".cache", "uw")
RESULTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RESULTS.md")


def attach_levels(rows, client):
    """Join each signal (or key) row to its D-1 levels using the cache only. Returns (complete rows with a
    `levels` DayLevels attached, Counter of exclusion reasons). Never touches the API."""
    complete, excluded, memo = [], Counter(), {}
    for r in rows:
        pair = (r["ticker"], r["prior_date"])
        if pair not in memo:
            (_, dp_path, dp_params), (_, gex_path, gex_params) = levels.requests_for(*pair)
            dp_raw, gex_raw = client.peek(dp_path, dp_params), client.peek(gex_path, gex_params)
            has_dp = levels.parse_dp(pair[0], dp_raw) is not None
            has_gex = levels.parse_gex(pair[0], gex_raw) is not None
            memo[pair] = (levels.DayLevels.from_responses(pair[0], dp_raw, gex_raw), has_dp, has_gex)
        lv, has_dp, has_gex = memo[pair]
        if lv is None:
            excluded["no_dark_pool_and_no_gex" if not has_dp and not has_gex
                     else "no_dark_pool" if not has_dp else "no_gex"] += 1
        else:
            complete.append(dict(r, levels=lv))
    return complete, excluded


def group_rows(sigs, level_of):
    """H1 and H2 rows for `level_of(signal) -> DayLevels`. H2 skips signals with no gamma flip or an entry
    exactly on it (counted by the caller via the returned Counter)."""
    h1, h2, skipped = [], [], Counter()
    for s in sigs:
        lv = level_of(s)
        h1.append({"date": s["date"], "group": "A" if levels.has_obstacle(s["entry"], s["target"], lv.all_prices) else "B",
                   "y": s["r"]})
        below = levels.below_gamma_flip(s["entry"], lv.gamma_flip)
        if below is None:
            skipped["no_gamma_flip" if lv.gamma_flip is None else "entry_on_flip"] += 1
        else:
            h2.append({"date": s["date"], "group": "A" if below else "B", "y": s["r"]})
    return h1, h2, skipped


def placebo_levels(sigs, seed=protocol.PLACEBO_SEED):
    """One seeded placebo world: every signal's levels shifted, drawn in (date, ticker) order so the result does
    not depend on the row order. Returns {id(signal): shifted DayLevels}."""
    rng = levels.placebo_rng(seed)
    return {id(s): s["levels"].shifted(rng) for s in sorted(sigs, key=lambda s: (s["date"], s["ticker"]))}


def summarise(name, rows, direction, placebo_rows):
    """Everything registered for one hypothesis, before Holm (which needs both p-values)."""
    n_a, n_b = sum(r["group"] == "A" for r in rows), sum(r["group"] == "B" for r in rows)
    boot = stats.day_cluster_bootstrap(rows)
    return {"name": name, "direction": direction, "n": len(rows), "n_a": n_a, "n_b": n_b,
            "share_a": n_a / len(rows) if rows else None,
            "mean_a": (sum(r["y"] for r in rows if r["group"] == "A") / n_a) if n_a else None,
            "mean_b": (sum(r["y"] for r in rows if r["group"] == "B") / n_b) if n_b else None,
            "unconditional_mean": (sum(r["y"] for r in rows) / len(rows)) if rows else None,
            "effect": stats.effect(rows), "naive_t": stats.welch_t(rows), "bootstrap": boot,
            "halves": stats.half_split(rows), "placebo_effect": stats.effect(placebo_rows)}


def run_analysis(sigs, excluded=None):
    """Pure function over signals that already carry `levels`. Returns the full result dict."""
    real_h1, real_h2, h2_skipped = group_rows(sigs, lambda s: s["levels"])
    shifted = placebo_levels(sigs)
    plc_h1, plc_h2, _ = group_rows(sigs, lambda s: shifted[id(s)])
    hyps = {"H1": summarise("H1 obstacle in the entry->3R path (obstacle - none)", real_h1, protocol.H1_DIRECTION, plc_h1),
            "H2": summarise("H2 entry below gamma_flip (below - above)", real_h2, protocol.H2_DIRECTION, plc_h2)}
    pvals = {k: h["bootstrap"]["p"] for k, h in hyps.items() if h["bootstrap"]}
    adjusted = stats.holm(pvals) if len(pvals) == len(hyps) else {}
    for k, h in hyps.items():
        h["p_holm"] = adjusted.get(k)
        halves = h["halves"] or {}
        h["supported"], h["failed"] = stats.hypothesis_verdict(
            h["direction"], h["effect"], h["p_holm"], halves.get("first"), halves.get("second"), h["placebo_effect"],
            placebo_required=protocol.PLACEBO_REQUIRED[k])
    status = stats.study_status(len(sigs))
    return {"n_complete": len(sigs), "status": status, "excluded": dict(excluded or {}),
            "h2_skipped": dict(h2_skipped), "hypotheses": hyps,
            "verdict": "UNDERPOWERED -- NO VERDICT" if status == "UNDERPOWERED" else
                       {k: ("SUPPORTED" if h["supported"] else "NOT SUPPORTED") for k, h in hyps.items()}}


def _fmt(x, spec="+.3f"):
    return "n/a" if x is None else format(x, spec)


def render(res):
    lines = [f"signals with complete D-1 data: {res['n_complete']:,} (registered minimum {protocol.MIN_SIGNALS:,}) "
             f"| excluded: {res['excluded'] or 'none'}"]
    if res["status"] == "UNDERPOWERED":
        lines.append("!! UNDERPOWERED -- NO VERDICT. The numbers below are descriptive only.")
    for key, h in res["hypotheses"].items():
        b, half = h["bootstrap"], h["halves"] or {}
        lines += ["", h["name"],
                  f"  n={h['n']:,} (A {h['n_a']:,} = {_fmt(h['share_a'] and 100 * h['share_a'], '.1f')}%, B {h['n_b']:,}) "
                  f"| mean R: A {_fmt(h['mean_a'])}  B {_fmt(h['mean_b'])}  all {_fmt(h['unconditional_mean'])}",
                  f"  effect {_fmt(h['effect'])}R | 95% CI (day-clustered bootstrap) "
                  f"[{_fmt(b and b['lo'])}, {_fmt(b and b['hi'])}] | p {_fmt(b and b['p'], '.4f')} "
                  f"| Holm p {_fmt(h['p_holm'], '.4f')} | naive t {_fmt(h['naive_t'], '.2f')} (not used)",
                  f"  halves (cut {half.get('cut')}): first {_fmt(half.get('first'))} (n={half.get('n_first')}), "
                  f"second {_fmt(half.get('second'))} (n={half.get('n_second')})",
                  f"  placebo effect {_fmt(h['placebo_effect'])}R " +
                  (f"(must be < {protocol.PLACEBO_MAX_RATIO} x |real|)" if protocol.PLACEBO_REQUIRED[key]
                   else "(informational only -- no placebo is registered for this hypothesis)"),
                  f"  -> {'SUPPORTED' if h['supported'] else 'NOT SUPPORTED'}" +
                  ("" if h["supported"] else f" (failed: {', '.join(h['failed'])})")]
    if res["h2_skipped"]:
        lines += ["", f"H2 excluded (no usable flip): {res['h2_skipped']}"]
    lines += ["", f"VERDICT: {res['verdict']}"]
    return "\n".join(lines)


def cmd_coverage(args, client):
    keys = load_keys(args.cache_dir)
    complete, excluded = attach_levels(keys, client)
    print(f"{len(keys):,} signals | complete D-1 data: {len(complete):,} | excluded: {dict(excluded) or 'none'}")
    print(f"registered minimum for a verdict: {protocol.MIN_SIGNALS:,} -> {stats.study_status(len(complete))}")


def cmd_analyze(args, client):
    marker_path = os.path.join(args.cache_dir, protocol.ANALYSIS_MARKER_FILE)
    marker = None
    if os.path.exists(marker_path):
        if not args.allow_rerun:
            raise SystemExit(f"{marker_path} exists: the analysis has already been run once, and the registration "
                             f"allows one run. Pass --allow-rerun to run again (the rerun is logged in the marker).")
        with open(marker_path, encoding="utf-8") as f:
            marker = json.load(f)
    complete, excluded = attach_levels(load_signals(args.cache_dir), client)
    res = run_analysis(complete, excluded)
    text = render(res)
    print(text)
    now = datetime.now(timezone.utc).isoformat()
    if marker is None:
        marker = {"first_run": now, "reruns": [], "verdict": res["verdict"]}
    else:
        marker["reruns"].append({"at": now, "verdict": res["verdict"]})
    with open(marker_path, "w", encoding="utf-8") as f:
        json.dump(marker, f, indent=2)
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:     # aggregates only -- no UW data, safe to commit
        f.write("# ARGUS-filter study results\n\nGenerated by `python -m research.argus_filter.analyze` "
                f"({now}). Aggregate statistics only.\n\n```\n{text}\n```\n")
    print(f"\nwrote {RESULTS_FILE}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", action="store_true", help="count signals with complete UW data; reads no outcomes")
    ap.add_argument("--allow-rerun", action="store_true")
    ap.add_argument("--cache-dir", default=CACHE_DIR)
    args = ap.parse_args()
    client = CachingClient(None, UW_CACHE_DIR)               # cache only: the analysis never calls the API
    (cmd_coverage if args.coverage else cmd_analyze)(args, client)


if __name__ == "__main__":
    load_dotenv()
    main()
