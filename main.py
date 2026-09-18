"""
Dark Pool + GEX Scanner -- CLI entry point.
Usage:
    python main.py scan SPY [--date YYYY-MM-DD] [--block-floor 200000]
    python main.py recent [--min-premium 500000]
"""
import argparse
import sys

from dotenv import load_dotenv

from src.uw_client import UnusualWhalesClient, UnusualWhalesAuthError
from src import darkpool, gex, flow, analysis, report


def cmd_scan(args):
    client = UnusualWhalesClient()

    prints = darkpool.ticker_prints(client, args.ticker, date=args.date)
    levels = darkpool.price_levels(client, args.ticker, date=args.date)
    gex_data = gex.gex_levels(client, args.ticker, date=args.date)
    alerts = flow.flow_alerts(client, ticker=args.ticker)

    blocks = analysis.block_prints(prints, notional_floor=args.block_floor)
    confluence = analysis.price_level_confluence(levels, gex_data)
    bias = analysis.flow_bias(alerts)

    print(f"\n=== {args.ticker} -- Dark Pool + GEX Scan ({gex_data.date}) ===\n")
    print(f"GEX ({gex_data.source}): call_wall={gex_data.call_wall}  put_wall={gex_data.put_wall}  "
          f"gamma_flip={gex_data.gamma_flip}  gamma_magnet={gex_data.gamma_magnet}")
    print(f"\nDark pool block prints (>= ${args.block_floor:,.0f} notional): {len(blocks)}")
    for b in blocks[:10]:
        print(f"  {b.executed_at}  {b.size:>8,} @ ${b.price:<10.2f}  ${b.notional:>14,.0f}  {b.market_center}")

    print(f"\nDark-pool price-level / GEX confluence (<=0.5% apart): {len(confluence)}")
    for c in confluence:
        print(f"  ${c['price']:.2f} near {c['gex_level']}=${c['gex_price']:.2f} "
              f"({c['distance_pct']}% away, {c['dark_pool_share_pct']}% dark-pool volume)")

    print(f"\nOptions flow bias: {bias['net_bias']}  "
          f"(n={bias['n']}, bullish ${bias['bullish_premium']:,.0f} vs bearish ${bias['bearish_premium']:,.0f}, "
          f"{bias['sweep_count']} sweeps)")

    if args.html:
        page = report.render_html(args.ticker, gex_data, levels, blocks, confluence, bias, args.block_floor)
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(page)
        print(f"\nHTML report written to {args.html}")


def cmd_recent(args):
    client = UnusualWhalesClient()
    prints = darkpool.recent_prints(client, min_premium=args.min_premium)
    blocks = analysis.block_prints(prints, notional_floor=args.block_floor)

    print(f"\n=== Market-wide recent dark pool block prints (>= ${args.block_floor:,.0f}) ===\n")
    for b in blocks[:25]:
        print(f"  {b.executed_at}  {b.ticker:<6}  {b.size:>8,} @ ${b.price:<10.2f}  ${b.notional:>14,.0f}")


def main():
    parser = argparse.ArgumentParser(description="Unusual Whales dark pool + GEX scanner")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Scan a single ticker")
    scan.add_argument("ticker")
    scan.add_argument("--date", default=None)
    scan.add_argument("--block-floor", type=float, default=analysis.DEFAULT_BLOCK_NOTIONAL_FLOOR)
    scan.add_argument("--html", default=None, help="Also write a self-contained HTML report to this path")
    scan.set_defaults(func=cmd_scan)

    recent = sub.add_parser("recent", help="Market-wide recent dark pool prints")
    recent.add_argument("--min-premium", type=float, default=None)
    recent.add_argument("--block-floor", type=float, default=analysis.DEFAULT_BLOCK_NOTIONAL_FLOOR)
    recent.set_defaults(func=cmd_recent)

    args = parser.parse_args()
    try:
        args.func(args)
    except UnusualWhalesAuthError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    load_dotenv()
    main()
