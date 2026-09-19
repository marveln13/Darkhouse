"""
Do dark-pool x GEX confluence levels attract price reaction?

    python -m research.run --tickers SPY,QQQ,NVDA,TSLA --days 250 [--k 0.5] [--horizon 4] [--top-n 5]

For each ticker and each consecutive trading-day pair (D, D+1): pull UW's
dark-pool price levels and GEX levels for D, label them, and measure how
price reacts when it first touches each level on D+1 (bars are ARGUS's
cached M30 series, read-only). Raw UW responses are cached in .cache/
(gitignored) so re-runs cost no API quota.
"""
import argparse
import os

import requests
from dotenv import load_dotenv

from src import darkpool, gex
from src.uw_client import UnusualWhalesClient

from . import reaction
from .bars import day_ranges, load_m30
from .caching_client import CachingClient
from .levels import DEFAULT_PROXIMITY_PCT, label_levels

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ROOT = os.path.join(REPO_ROOT, "..", "ai-trading-desk-2")
GROUPS = ("confluence", "dp_only", "gex_only", "placebo")


def collect_events(client, ticker, bars, days, args):
    ranges = day_ranges(bars)
    dates = sorted(ranges)[-(days + 1):]
    events, skipped = [], 0
    for d, nxt in zip(dates, dates[1:]):
        try:
            levels = darkpool.price_levels(client, ticker, date=d)
            gex_data = gex.gex_levels(client, ticker, date=d, source=args.gex_source)
        except (requests.HTTPError, KeyError):
            skipped += 1
            continue
        labelled = label_levels(levels, gex_data, top_n=args.top_n, proximity_pct=args.proximity)
        events.extend(reaction.events_for_day(ticker, nxt, bars, ranges[nxt], labelled,
                                              k=args.k, horizon=args.horizon))
    return events, skipped


def report(events):
    print(f"\n{'group':<12}{'events':>8}{'hold':>7}{'break':>7}{'timeout':>9}{'hold rate':>11}")
    for g in GROUPS:
        ev = [e for e in events if e["group"] == g]
        c = {o: sum(1 for e in ev if e["outcome"] == o) for o in ("hold", "break", "timeout")}
        rate = reaction.hold_rate(ev)
        rate_txt = "n/a" if rate is None else f"{100 * rate:.1f}%"
        print(f"{g:<12}{len(ev):>8}{c['hold']:>7}{c['break']:>7}{c['timeout']:>9}{rate_txt:>11}")
    print("\nConfluence vs each control (unit = ticker-day; Welch t, normal-approx p):")
    for b in ("dp_only", "gex_only", "placebo"):
        r = reaction.compare_groups(events, "confluence", b)
        if r["t"] is None:
            print(f"  vs {b:<9} insufficient data (n={r['n_a']}/{r['n_b']})")
        else:
            print(f"  vs {b:<9} {100 * r['hold_a']:.1f}% vs {100 * r['hold_b']:.1f}%  "
                  f"diff {100 * (r['hold_a'] - r['hold_b']):+.1f} pts  t={r['t']:.2f}  "
                  f"p={r['p']:.3f}  (n={r['n_a']}/{r['n_b']})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--argus-root", default=DEFAULT_ROOT)
    ap.add_argument("--tickers", default="SPY,QQQ,NVDA,TSLA")
    ap.add_argument("--days", type=int, default=250)
    ap.add_argument("--k", type=float, default=0.5, help="reaction size in ATRs")
    ap.add_argument("--horizon", type=int, default=4, help="M30 bars to wait for a reaction")
    ap.add_argument("--top-n", type=int, default=5, help="heavy dark-pool levels per day")
    ap.add_argument("--proximity", type=float, default=DEFAULT_PROXIMITY_PCT, help="%% distance that counts as the same level")
    ap.add_argument("--gex-source", default="oi", choices=("oi", "vol"))
    args = ap.parse_args()

    client = CachingClient(UnusualWhalesClient(), os.path.join(REPO_ROOT, ".cache", "uw"))
    events = []
    for t in args.tickers.split(","):
        ev, skipped = collect_events(client, t, load_m30(args.argus_root, t), args.days, args)
        print(f"{t}: {len(ev)} touch events ({skipped} days skipped: no UW data)")
        events.extend(ev)
    report(events)


if __name__ == "__main__":
    load_dotenv()
    main()
