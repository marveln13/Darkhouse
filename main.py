"""
Black Lantern -- dark pool + GEX scanner on the Unusual Whales API. CLI entry point.
Usage:
    python main.py demo [--out reports/demo.html] [--open]          # no API key needed (synthetic data)
    python main.py scan SPY [--date YYYY-MM-DD] [--html out.html] [--open] [--candle-size 5m] [--same-day-levels]
    python main.py recent [--min-premium 500000]
"""
import argparse
import os
import pathlib
import sys
import webbrowser
from datetime import date as date_cls, datetime, timedelta

from dotenv import load_dotenv

from src.uw_client import UnusualWhalesClient, UnusualWhalesAuthError
from src import darkpool, gex, flow, analysis, report, ohlc, chart

PRIOR_SESSION_LOOKBACK = 6      # weekdays to step back past holidays when looking for the prior session's levels
SAME_DAY_NOTE = " (same-day end-of-day snapshot -- hindsight, not what was known during the session)"
PRIOR_NOTE = " (the prior session's end-of-day levels -- what was known going into this session)"


def session_date(candles):
    """ET trading date of a list of candles, or None."""
    if not candles:
        return None
    start = datetime.fromisoformat(candles[0].start_time.replace("Z", "+00:00"))
    return start.astimezone(chart.ET).date().isoformat()


def prior_weekdays(d, n=PRIOR_SESSION_LOOKBACK):
    day = date_cls.fromisoformat(d)
    out = []
    while len(out) < n:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            out.append(day.isoformat())
    return out


def prior_session_levels(client, ticker, d):
    """(date, price levels, gex levels) for the most recent session strictly before `d` that has dark-pool levels.
    Stepping over holidays: a date with no levels is skipped. Returns (None, None, None) when nothing is found."""
    for day in prior_weekdays(d):
        levels = darkpool.price_levels(client, ticker, date=day)
        if levels.levels:
            return day, levels, gex.gex_levels(client, ticker, date=day)
    return None, None, None


def write_report(page, path, open_it):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    print(f"\nHTML report written to {path}")
    if open_it:
        webbrowser.open(path.resolve().as_uri())


def cmd_scan(args):
    client = UnusualWhalesClient()
    candle_size = getattr(args, "candle_size", "5m")
    same_day = getattr(args, "same_day_levels", False)

    candles = ohlc.candles(client, args.ticker, candle_size=candle_size, date=args.date)
    day = args.date or session_date(candles)
    if same_day or day is None:
        levels_date, note = day, SAME_DAY_NOTE
        levels = darkpool.price_levels(client, args.ticker, date=args.date)
        gex_data = gex.gex_levels(client, args.ticker, date=args.date)
    else:
        levels_date, levels, gex_data = prior_session_levels(client, args.ticker, day)
        note = PRIOR_NOTE
        if levels is None:
            print(f"no dark-pool levels found in the {PRIOR_SESSION_LOOKBACK} weekdays before {day}", file=sys.stderr)
            sys.exit(1)

    prints, complete = darkpool.prints_for_day(client, args.ticker, day, min_premium=args.block_floor,
                                               max_pages=getattr(args, "max_pages", 10))
    earliest = min((p.executed_at for p in prints), default="n/a")
    blocks_note = "" if complete else (
        f"Block prints truncated: the page cap ran out before the open, so the earliest prints are missing "
        f"(earliest shown {earliest}). Raise --block-floor or --max-pages.")
    alerts = flow.flow_alerts(client, ticker=args.ticker)
    strikes = gex.spot_gex_by_strike(client, args.ticker, date=levels_date)
    top_strikes = analysis.top_gamma_strikes(strikes, source="vol", n=5)

    blocks = analysis.block_prints(prints, notional_floor=args.block_floor)
    confluence = analysis.price_level_confluence(levels, gex_data)
    bias = analysis.flow_bias(alerts)

    print(f"\n=== {args.ticker} -- Black Lantern scan, session {day} ===\n")
    print(f"Levels from {levels_date}{note}")
    print(f"GEX ({gex_data.source}): call_wall={gex_data.call_wall}  put_wall={gex_data.put_wall}  "
          f"gamma_flip={gex_data.gamma_flip}  gamma_magnet={gex_data.gamma_magnet}")
    if candles:
        print(f"Session ({len(candles)} x {candle_size} candles): open {candles[0].open:.2f}  "
              f"high {max(c.high for c in candles):.2f}  low {min(c.low for c in candles):.2f}  "
              f"last {candles[-1].close:.2f}")
    print("\nTop gamma strikes (net, volume basis):")
    for s in top_strikes:
        print(f"  ${s.strike:<9.2f} net {s.net('vol') / 1e6:>10,.1f}M  "
              f"(call {s.call_gamma_vol / 1e6:,.1f}M / put {s.put_gamma_vol / 1e6:,.1f}M)")
    print(f"\nDark pool block prints, regular hours (>= ${args.block_floor:,.0f} notional): {len(blocks)}"
          f"{'' if complete else '  [TRUNCATED -- earliest prints missing]'}")
    for b in blocks[:10]:
        print(f"  {b.executed_at}  {b.size:>8,} @ ${b.price:<10.2f}  ${b.notional:>14,.0f}  {b.market_center}")

    print(f"\nDark-pool price-level / GEX confluence (<=0.1% apart): {len(confluence)}")
    for c in confluence[:10]:
        print(f"  ${c['price']:.2f} near {c['gex_level']}=${c['gex_price']:.2f} "
              f"({c['distance_pct']}% away, {c['dark_pool_share_pct']}% dark-pool volume)")

    print(f"\nOptions flow bias: {bias['net_bias']}  "
          f"(n={bias['n']}, bullish ${bias['bullish_premium']:,.0f} vs bearish ${bias['bearish_premium']:,.0f}, "
          f"{bias['sweep_count']} sweeps)")

    if args.html:
        chart_html = chart.render_chart_svg(
            chart.build_chart(candles, levels, gex_data, blocks, confluence, levels_date=levels_date, levels_note=note,
                              blocks_note=blocks_note))
        page = report.render_html(args.ticker, gex_data, levels, blocks, confluence, bias,
                                  args.block_floor, top_strikes=top_strikes, chart_html=chart_html, session=day)
        write_report(page, args.html, getattr(args, "open", False))


def cmd_demo(args):
    from src import demo
    d = demo.build()
    blocks = analysis.block_prints(d["prints"], notional_floor=args.block_floor)
    confluence = analysis.price_level_confluence(d["levels"], d["gex"])
    chart_html = chart.render_chart_svg(chart.build_chart(
        d["candles"], d["levels"], d["gex"], blocks, confluence, levels_date=d["levels_date"], levels_note=PRIOR_NOTE))
    page = report.render_html(d["ticker"], d["gex"], d["levels"], blocks, confluence, analysis.flow_bias(d["alerts"]),
                              args.block_floor, top_strikes=d["top_strikes"], chart_html=chart_html, banner=demo.BANNER,
                              session=demo.SESSION_DATE)
    write_report(page, args.out, args.open)
    if args.svg:
        path = pathlib.Path(args.svg)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(chart.standalone_svg(chart.build_chart(
            d["candles"], d["levels"], d["gex"], blocks, confluence, levels_date=d["levels_date"],
            levels_note=PRIOR_NOTE)), encoding="utf-8")
        print(f"Standalone chart SVG written to {path}")


def cmd_recent(args):
    client = UnusualWhalesClient()
    prints = darkpool.recent_prints(client, min_premium=args.min_premium)
    blocks = analysis.block_prints(prints, notional_floor=args.block_floor)

    print(f"\n=== Market-wide recent dark pool block prints (>= ${args.block_floor:,.0f}) ===\n")
    for b in blocks[:25]:
        print(f"  {b.executed_at}  {b.ticker:<6}  {b.size:>8,} @ ${b.price:<10.2f}  ${b.notional:>14,.0f}")


def main():
    parser = argparse.ArgumentParser(description="Black Lantern -- Unusual Whales dark pool + GEX scanner")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Scan a single ticker")
    scan.add_argument("ticker")
    scan.add_argument("--date", default=None)
    scan.add_argument("--block-floor", type=float, default=analysis.DEFAULT_BLOCK_NOTIONAL_FLOOR)
    scan.add_argument("--html", default=None, help="Also write a self-contained HTML report to this path")
    scan.add_argument("--open", action="store_true", help="Open the HTML report in the browser")
    scan.add_argument("--max-pages", type=int, default=10, help="Dark-pool pages (500 prints each) to walk back")
    scan.add_argument("--candle-size", default="5m", choices=ohlc.CANDLE_SIZES)
    scan.add_argument("--same-day-levels", action="store_true",
                      help="Draw the session's own end-of-day levels (hindsight) instead of the prior session's")
    scan.set_defaults(func=cmd_scan)

    demo = sub.add_parser("demo", help="Render the report from synthetic data (no API key needed)")
    demo.add_argument("--out", default=os.path.join("reports", "demo.html"))
    demo.add_argument("--open", action="store_true")
    demo.add_argument("--svg", default=None, help="Also write the chart alone as a standalone .svg (README image)")
    demo.add_argument("--block-floor", type=float, default=analysis.DEFAULT_BLOCK_NOTIONAL_FLOOR)
    demo.set_defaults(func=cmd_demo)

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
