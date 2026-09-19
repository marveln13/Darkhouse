"""
Flow conviction card: one contract-day, scored component by component, with the
size vocabulary alongside as a REFERENCE (the score does not set size -- that
link is only justified if the pre-registered study supports it).

    python -m research.flow.card GOOGL261002C00355000 2026-09-10 [--equity 100000] [--out card.html]

Reads the locally cached contract history and daily closes only (no API calls);
pass --fetch to allow one API request if the contract isn't cached.
"""
import argparse
import json
import os
from html import escape

from dotenv import load_dotenv

from research.caching_client import CachingClient
from research.flow import score, sizing
from research.flow.events import event_from_contract_day

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#14181f;--muted:#5d6675;--line:#dfe3ea;--accent:#2a5bd7;
--good:#15803d;--bad:#b91c1c;--mid:#b45309}
@media (prefers-color-scheme:dark){:root{--bg:#0e1116;--card:#171b22;--ink:#e8ebf0;--muted:#98a2b3;
--line:#2a313c;--accent:#7aa2ff;--good:#4ade80;--bad:#f87171;--mid:#fbbf24}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
main{max-width:760px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:20px;margin:0}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 10px}
.sub{color:var(--muted);margin:2px 0 18px}
section{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:16px;margin-bottom:14px}
.head{display:flex;gap:16px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.big{font-size:44px;font-weight:700;line-height:1;font-variant-numeric:tabular-nums}
.big small{font-size:18px;color:var(--muted);font-weight:500}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;border:1px solid var(--line);font-weight:600;font-size:13px}
.bullish{color:var(--good)}.bearish{color:var(--bad)}.mid{color:var(--mid)}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600;font-size:13px}
td.n,th.n{text-align:right}
.bar{display:flex;gap:3px}.bar i{width:14px;height:10px;border-radius:2px;background:var(--line)}
.bar i.on{background:var(--accent)}
.note{color:var(--muted);font-size:13px}
.wrap{overflow-x:auto}
"""


def _component_rows(event):
    parts, eod = score.components(event), event.eod
    ask = eod.ask_share
    facts = {
        "size": (2, f"day premium ${eod.total_premium:,.0f}  (1 pt >= ${score.SIZE_MID:,}, 2 pts >= ${score.SIZE_HIGH:,})"),
        "opening": (2, f"volume / open interest {eod.vol_oi or 0:,.1f}x  (1 pt >= {score.VOL_OI_MID:g}x, 2 pts >= {score.VOL_OI_HIGH:g}x)"),
        "aggression": (1, f"{'n/a' if ask is None else f'{100 * ask:.0f}% ask / {100 * (1 - ask):.0f}% bid'}  (needs >= {100 * score.DOMINANCE:.0f}% on one side)"),
        "floor": (1, f"{100 * eod.floor_share:.0f}% floor volume  (needs >= {100 * score.FLOOR_SHARE:.0f}%)"),
        "single_leg": (1, f"{100 * eod.multileg_share:.0f}% multi-leg  (needs < {100 * score.MULTILEG_MAX:.0f}%)"),
        "horizon": (1, f"{event.dte} days to expiry  (needs {score.DTE_MIN}-{score.DTE_MAX})"),
        "otm": (1, f"{event.otm_pct:.1f}% out of the money  (needs {score.OTM_MIN:g}-{score.OTM_MAX:g}%)"),
    }
    rows = []
    for name, (maximum, text) in facts.items():
        pts = parts[name]
        pips = "".join(f'<i class="on"></i>' if k < pts else "<i></i>" for k in range(maximum))
        rows.append(f'<tr><td>{escape(name.replace("_", " "))}</td><td><div class="bar">{pips}</div></td>'
                    f'<td class="n">{pts}/{maximum}</td><td>{escape(text)}</td></tr>')
    return "".join(rows)


def _size_rows(equity, price):
    out = []
    for term, n in (("lotto", sizing.lotto_contracts(equity, price)),
                    ("lite_starter", sizing.contracts("lite_starter", equity, price)),
                    ("half", sizing.contracts("half", equity, price)),
                    ("heavy (full size)", sizing.contracts("full", equity, price))):
        cost = n * price * sizing.CONTRACT_MULTIPLIER
        out.append(f'<tr><td>{escape(term.replace("_", " "))}</td><td class="n">{n}</td>'
                   f'<td class="n">${cost:,.0f}</td><td class="n">{100 * cost / equity:.2f}%</td></tr>')
    return "".join(out)


def render_card(event, equity):
    s, bucket, direction = score.score(event), score.bucket(event), score.direction(event)
    price = event.eod.last_price or event.first_price
    ladders = " &nbsp;|&nbsp; ".join(
        f"start {f}: " + (" &rarr; ".join(str(n) for n in sizing.scale_in_plan(equity, price, first=f)) or "not affordable")
        for f in sizing.FIRST_ENTRY_CHOICES)
    dir_html = ('<span class="pill">no side dominance</span>' if direction is None else
                f'<span class="pill {direction}">{direction}</span>')
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(event.chain)} flow conviction card</title><style>{_CSS}</style></head>
<body><main>
<section><div class="head">
<div><h1>{escape(event.ticker)} {event.strike:g} {escape(event.type)} &middot; exp {escape(event.expiry)}</h1>
<p class="sub">{escape(event.date)} &middot; {escape(event.chain)} &middot; {escape(sizing.tier(equity))} account (${equity:,.0f})</p>
{dir_html} <span class="pill mid">{escape(bucket)} conviction</span></div>
<div class="big">{s}<small> / 9</small></div></div></section>

<section><h2>How the score was built</h2><div class="wrap"><table>
<tr><th>Component</th><th></th><th class="n">Points</th><th>What the flow showed</th></tr>{_component_rows(event)}</table></div>
<p class="note">End-of-day contract stats. Thresholds are pre-registered and were not tuned on outcomes.</p></section>

<section><h2>Size vocabulary at ${price:.2f} per share (reference)</h2><div class="wrap"><table>
<tr><th>Size</th><th class="n">Contracts</th><th class="n">Premium</th><th class="n">% of account</th></tr>{_size_rows(equity, price)}</table></div>
<p class="note">Scale-in ladders to full size (adds of 2): {ladders}</p>
<p class="note">Full size and above is heavy. The score does not set size: that link is only justified if the pre-registered study supports it.</p></section>

<section><p class="note">Research score from Unusual Whales options data. Not investment advice, and not a validated trading signal: its predictive value is being tested in a pre-registered study.</p></section>
</main></body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("chain")
    ap.add_argument("date")
    ap.add_argument("--equity", type=float, default=100_000)
    ap.add_argument("--out", default="flow_card.html")
    ap.add_argument("--fetch", action="store_true", help="allow one UW API call if the contract isn't cached")
    args = ap.parse_args()

    inner = None
    if args.fetch:
        from src.uw_client import UnusualWhalesClient
        inner = UnusualWhalesClient()
    cache = CachingClient(inner, os.path.join(REPO_ROOT, ".cache", "uw"))
    path = f"/api/option-contract/{args.chain}/historic"
    hist = cache.get(path) if args.fetch else cache.peek(path)
    if hist is None:
        raise SystemExit("contract history not cached; rerun with --fetch to spend one API request")
    row = next((r for r in hist.get("chains", []) if r["date"] == args.date), None)
    if row is None:
        raise SystemExit(f"no daily row for {args.date}")
    ticker = args.chain[: args.chain.index(next(c for c in args.chain if c.isdigit()))]
    with open(os.path.join(REPO_ROOT, ".cache", "flow", "daily", f"{ticker}.json"), encoding="utf-8") as f:
        underlying = json.load(f)[args.date]
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(render_card(event_from_contract_day(args.chain, args.date, row, underlying), args.equity))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    load_dotenv()
    main()
