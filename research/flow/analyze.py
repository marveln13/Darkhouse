"""
Run the pre-registered flow conviction study (see protocol.py) on the
collected data.

    python -m research.flow.analyze [--argus-root PATH]

Reads cached UW responses only (never calls the API). Prints attrition counts,
per-bucket outcomes, and every registered test -- including the ones that fail.
"""
import argparse
import os
from collections import Counter

from research.caching_client import CachingClient
from research.flow import collect, outcomes, prices, protocol, score, stats
from research.flow.events import EodStats

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_ROOT = os.path.join(REPO_ROOT, "..", "ai-trading-desk-2")
PRICE_START, PRICE_END = "2025-09-01", "2026-09-19"


def build_rows(events, cache, closes_by_ticker, spy, cal, index):
    rows, drops = [], Counter()
    for e in events:
        hist = cache.peek(f"/api/option-contract/{e.chain}/historic")
        if hist is None:
            drops["not_enriched"] += 1
            continue
        by_date = {r["date"]: r for r in hist.get("chains", [])}
        day = by_date.get(e.date)
        if day is None:
            drops["no_eod_row"] += 1
            continue
        e.eod = EodStats.from_row(day)
        direction = score.direction(e)
        if direction is None:
            drops["no_side_dominance"] += 1
            continue
        ask_dominant = e.eod.ask_share is not None and e.eod.ask_share >= score.DOMINANCE
        row = {"date": e.date, "ticker": e.ticker, "chain": e.chain, "type": e.type, "score": score.score(e),
               "bucket": score.bucket(e), "direction": direction, "ask_dominant": ask_dominant,
               "u": outcomes.underlying_outcome(e.date, 1 if direction == "bullish" else -1,
                                                closes_by_ticker.get(e.ticker, {}), spy, cal, index),
               "gross": None, "net": None, "c_status": None}
        if ask_dominant:
            c = outcomes.contract_outcome(e.date, by_date, cal, index)
            row["c_status"] = c["status"]
            row["gross"], row["net"] = c.get("gross"), c.get("net")
        rows.append(row)
    return rows, drops


def _fmt(x, pct=True):
    return "n/a" if x is None else (f"{100 * x:+.2f}%" if pct else f"{x:+.3f}")


def report(rows, label, key, note=""):
    print(f"\n=== {label}  [{key}] {note}")
    table = stats.bucket_table(rows, key)
    print(f"  {'bucket':<6}{'n':>8}{'mean (winsor)':>16}{'median':>10}{'hit rate':>10}")
    for b in ("low", "mid", "high"):
        t = table[b]
        hit = "n/a" if t["hit_rate"] is None else f"{100 * t['hit_rate']:.1f}%"
        print(f"  {b:<6}{t['n']:>8}{_fmt(t['mean_w']):>16}{_fmt(t['median']):>10}{hit:>10}")
    diff = stats.high_minus_low(rows, key)
    boot, perm, split = stats.cluster_bootstrap(rows, key), stats.permutation_test(rows, key), stats.half_split(rows, key)
    rho = stats.spearman(rows, key)
    print(f"  high - low: {_fmt(diff)}", end="")
    if boot:
        print(f"   day-bootstrap 95% CI [{_fmt(boot['lo'])}, {_fmt(boot['hi'])}] p={boot['p_two_sided']:.3f}", end="")
    if perm:
        print(f"   permutation p={perm['p_two_sided']:.3f}", end="")
    print(f"\n  Spearman(score, outcome) = {'n/a' if rho is None else f'{rho:+.3f}'}", end="")
    if split:
        print(f"   half-split (cut {split['cut']}): first {_fmt(split['first_half'])} | second {_fmt(split['second_half'])}", end="")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--argus-root", default=DEFAULT_ROOT)
    args = ap.parse_args()

    cache = CachingClient(None, os.path.join(REPO_ROOT, ".cache", "uw"))
    events = collect.load_events()
    keep, sample = collect.enrichment_targets(events)
    tickers = sorted({e.ticker for e in keep + sample} | {protocol.BENCHMARK})
    closes = prices.fetch_daily_closes(tickers, PRICE_START, PRICE_END, prices.alpaca_keys(args.argus_root),
                                       os.path.join(REPO_ROOT, ".cache", "flow", "daily"))
    spy = closes[protocol.BENCHMARK]
    cal, index = outcomes.calendar_index(spy)

    rows, drops = build_rows(keep, cache, closes, spy, cal, index)
    print(f"events passing the cutoff: {len(keep):,} | analysed (directional, EOD row found): {len(rows):,} | dropped: {dict(drops)}")
    print("bucket sizes:", dict(Counter(r["bucket"] for r in rows)))

    report(rows, "OUTCOME 1: direction-signed underlying return, D close -> D+5 close, minus SPY", "u")
    followers = [r for r in rows if r["ask_dominant"]]
    print(f"\nask-dominant events (copyable by BUYING the contract): {len(followers):,}; "
          f"contract-outcome status by bucket:")
    for b in ("low", "mid", "high"):
        print(f"  {b:<5}", dict(Counter(r["c_status"] for r in followers if r["bucket"] == b)))
    report(followers, "OUTCOME 2 (gross): buy the contract, D+1 open -> D+6 avg", "gross")
    report(followers, "OUTCOME 2 (net of half-spread on entry and exit)", "net")

    srows, sdrops = build_rows(sample, cache, closes, spy, cal, index)
    hi_keep = sum(1 for r in rows if r["bucket"] == "high")
    hi_sample = sum(1 for r in srows if r["bucket"] == "high")
    excluded = len(events) - len(keep)
    est = hi_sample / max(1, len(srows)) * (excluded / max(1, len(sample))) * len(srows) if srows else 0
    print(f"\nLEAKAGE CHECK: {len(srows)} sampled below-cutoff events analysed, {hi_sample} scored high "
          f"({100 * hi_sample / max(1, len(srows)):.1f}% vs {100 * hi_keep / max(1, len(rows)):.1f}% above the cutoff). "
          f"Estimated high-score events the cutoff excluded: ~{est:,.0f} vs {hi_keep:,} kept.")


if __name__ == "__main__":
    main()
