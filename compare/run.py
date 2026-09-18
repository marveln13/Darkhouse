"""
Compare Unusual Whales data against ARGUS's own recorded data.

    python -m compare.run gex
    python -m compare.run darkpool --date 2026-09-18 [--tickers SPY,NVDA] [--top 8]
    python -m compare.run flow --dates 2026-09-16,2026-09-18 [--tickers SPY,QQQ,NVDA]

Reads ARGUS files read-only from --argus-root (default: the sibling
ai-trading-desk-2 checkout). Prints aggregate statistics only -- UW data is
personal-use, so nothing here saves or republishes raw UW responses.
"""
import argparse
import os
import statistics

from dotenv import load_dotenv

from src import gex
from src.uw_client import UnusualWhalesClient

from . import argus_logs, dark_pool_match, flow_agreement, gex_agreement, uw_fetch

DEFAULT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "ai-trading-desk-2")
MIN_ALIVE_RTH_BLOCKS = 1000  # fewer than this in a regular session = ARGUS's detector was down


def _pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def cmd_gex(args, client):
    cache = argus_logs.load_gex_cache(os.path.join(args.argus_root, "backtest", "data_cache", "gex_regime_spy_daily.json"))
    history = gex.greek_exposure_history(client, "SPY", timeframe=args.timeframe)
    print(f"ARGUS cached days: {len(cache)}   UW history rows: {len(history)}")
    for convention, r in gex_agreement.compare_gex(cache, history).items():
        z = "n/a" if r["z_vs_coinflip"] is None else f"{r['z_vs_coinflip']:.2f}"
        corr = "n/a" if r["pearson"] is None else f"{r['pearson']:.2f}"
        print(f"\n[{convention}] paired days n={r['n']}  sign agreement {_pct(r['sign_agreement'])}  "
              f"z vs coin-flip {z}  pearson {corr}  UW positive on {_pct(r['uw_positive_share'])} of days")
        if r["uw_sign_suspect"]:
            print("  WARNING: UW net is (almost) always one sign under this convention -- likely the wrong convention.")


def cmd_darkpool(args, client):
    blocks, bad = argus_logs.load_dark_pool_blocks(os.path.join(args.argus_root, "logs", "dark_pool_blocks.jsonl"))
    day = [b for b in blocks if argus_logs.et_date(b["dt"]) == args.date and argus_logs.is_regular_hours(b["dt"])]
    print(f"ARGUS blocks on {args.date} (regular hours): {len(day)}   (skipped {bad} corrupt lines in file)")
    if len(day) < MIN_ALIVE_RTH_BLOCKS:
        print(f"  ARGUS's detector looks DOWN this day (<{MIN_ALIVE_RTH_BLOCKS}) -- a comparison would measure the outage. Aborting.")
        return

    counts = {}
    for b in day:
        counts[b["ticker"]] = counts.get(b["ticker"], 0) + 1
    tickers = args.tickers.split(",") if args.tickers else [t for t, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:args.top]]

    tot = {"argus": 0, "uw": 0, "matched": 0}
    for t in tickers:
        mine = [b for b in day if b["ticker"] == t]
        if not mine:
            continue
        price = statistics.median(b["price"] for b in mine)
        min_size = int(0.9 * dark_pool_match.DEFAULT_MIN_NOTIONAL / price)
        uw = uw_fetch.fetch_dark_pool_day(client, t, args.date, min_size=min_size)
        r = dark_pool_match.match_blocks(mine, uw)
        lag = "n/a" if r["median_lag_s"] is None else f"{r['median_lag_s']:.1f}s"
        print(f"  {t:<6} ARGUS {r['n_argus']:>6}  UW>=$200k {r['n_uw']:>6}  matched {r['n_matched']:>6}  "
              f"ARGUS-covered {_pct(r['argus_match_rate'])}  UW-covered {_pct(r['uw_match_rate'])}  median lag {lag}")
        tot["argus"] += r["n_argus"]; tot["uw"] += r["n_uw"]; tot["matched"] += r["n_matched"]
    if tot["argus"]:
        print(f"\nALL: ARGUS {tot['argus']}  UW {tot['uw']}  matched {tot['matched']}  "
              f"ARGUS-covered {_pct(tot['matched'] / tot['argus'])}  UW-covered {_pct(tot['matched'] / tot['uw'] if tot['uw'] else None)}")


def cmd_flow(args, client):
    snaps, bad = argus_logs.load_flow_snapshots(os.path.join(args.argus_root, "logs", "options_flow_snapshots.jsonl"))
    argus_daily = flow_agreement.argus_daily_flow(snaps)
    dates = args.dates.split(",")
    tickers = args.tickers.split(",") if args.tickers else sorted({t for (_, t) in argus_daily})
    alerts_by_key = {}
    for d in dates:
        for t in tickers:
            alerts_by_key[(d, t)] = uw_fetch.fetch_flow_alerts_day(client, t, d)
    r = flow_agreement.compare_flow({k: v for k, v in argus_daily.items() if k[0] in dates},
                                    flow_agreement.uw_daily_flow(alerts_by_key))
    z = "n/a" if r["z_vs_coinflip"] is None else f"{r['z_vs_coinflip']:.2f}"
    print(f"ticker-days compared n={r['n']}  sign agreement {_pct(r['sign_agreement'])}  z vs coin-flip {z}  "
          f"pearson(signed-log) {r['pearson_signed_log']}")


def main():
    ap = argparse.ArgumentParser(description="Compare Unusual Whales data with ARGUS's recorded data")
    ap.add_argument("--argus-root", default=DEFAULT_ROOT)
    sub = ap.add_subparsers(dest="command", required=True)

    g = sub.add_parser("gex"); g.add_argument("--timeframe", default=None); g.set_defaults(func=cmd_gex)
    d = sub.add_parser("darkpool"); d.add_argument("--date", required=True)
    d.add_argument("--tickers"); d.add_argument("--top", type=int, default=8); d.set_defaults(func=cmd_darkpool)
    f = sub.add_parser("flow"); f.add_argument("--dates", required=True)
    f.add_argument("--tickers"); f.set_defaults(func=cmd_flow)

    args = ap.parse_args()
    args.func(args, UnusualWhalesClient())


if __name__ == "__main__":
    load_dotenv()
    main()
