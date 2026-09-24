"""
Self-contained HTML report: a price ladder of dark-pool volume by level
with the GEX structural levels (call wall / put wall / gamma flip /
gamma magnet) interleaved at their prices, so confluence is visible at a
glance. Pure string rendering over already-parsed models -- no network,
no external assets.
"""
from html import escape

from .chart import CHART_CSS

BRAND = "Darkhouse"

GEX_LABELS = {
    "call_wall": "Call wall",
    "put_wall": "Put wall",
    "gamma_flip": "Gamma flip",
    "gamma_magnet": "Gamma magnet",
}

_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#14181f;--muted:#5d6675;--line:#dfe3ea;
--bar:#3b6fd4;--gex:#c2410c;--good:#0072b2;--bad:#d55e00}
@media (prefers-color-scheme:dark){:root{--bg:#0e1116;--card:#171b22;--ink:#e8ebf0;
--muted:#98a2b3;--line:#2a313c;--bar:#6b9bf5;--gex:#fb923c;--good:#56b4e9;--bad:#f07a2e}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
main{max-width:920px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 0 12px}
.sub{color:var(--muted);margin:0 0 20px}
section{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:16px;margin-bottom:16px}
.ladder{display:grid;grid-template-columns:84px 1fr 200px;gap:6px 12px;align-items:center;font-variant-numeric:tabular-nums}
.ladder .price{text-align:right}
.track{height:14px;background:var(--line);border-radius:2px;overflow:hidden}
.fill{height:100%;background:var(--bar)}
.gexrow{grid-column:1/-1;border-top:2px solid var(--gex);color:var(--gex);font-weight:600;padding-top:2px}
.note{color:var(--muted);font-size:13px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600;font-size:13px}
td.n,th.n{text-align:right}
.bull{color:var(--good)}.bear{color:var(--bad)}
.wrap{overflow-x:auto}
.brand{font-weight:700;letter-spacing:.14em;text-transform:uppercase;font-size:12px;color:var(--gex);margin:0 0 6px}
.banner{border:1px dashed var(--gex);color:var(--gex);border-radius:6px;padding:8px 12px;margin:0 0 14px;font-weight:600}
"""


def _ladder(levels, gex):
    entries = [("level", lv.price, lv) for lv in levels.levels]
    for key, label in GEX_LABELS.items():
        price = getattr(gex, key)
        if price is not None:
            entries.append(("gex", price, label))
    if not entries:
        return '<p class="note">No price-level data.</p>'

    max_vol = max((lv.dark_pool_volume for lv in levels.levels), default=0) or 1
    rows = []
    for kind, price, item in sorted(entries, key=lambda e: e[1], reverse=True):
        if kind == "gex":
            rows.append(f'<div class="gexrow">{escape(item)} &mdash; ${price:,.2f}</div>')
        else:
            width = 100.0 * item.dark_pool_volume / max_vol
            rows.append(
                f'<div class="price">${price:,.2f}</div>'
                f'<div class="track"><div class="fill" style="width:{width:.1f}%"></div></div>'
                f'<div>{item.dark_pool_volume:,} shs ({item.dark_pool_share_pct}% dark)</div>'
            )
    return f'<div class="ladder">{"".join(rows)}</div>'


def _blocks_table(blocks, limit=15):
    if not blocks:
        return '<p class="note">No block prints at this notional floor.</p>'
    rows = "".join(
        f'<tr><td>{escape(b.executed_at)}</td><td class="n">{b.size:,}</td>'
        f'<td class="n">${b.price:,.2f}</td><td class="n">${b.notional:,.0f}</td>'
        f'<td>{escape(b.market_center)}</td></tr>'
        for b in blocks[:limit]
    )
    return (
        '<div class="wrap"><table><tr><th>Executed (UTC)</th><th class="n">Shares</th>'
        '<th class="n">Price</th><th class="n">Notional</th><th>Venue</th></tr>'
        f'{rows}</table></div>'
    )


def _confluence_table(confluence):
    if not confluence:
        return '<p class="note">No dark-pool level sits within the proximity band of a GEX level.</p>'
    rows = "".join(
        f'<tr><td class="n">${c["price"]:,.2f}</td>'
        f'<td>{escape(GEX_LABELS.get(c["gex_level"], c["gex_level"]))} (${c["gex_price"]:,.2f})</td>'
        f'<td class="n">{c["distance_pct"]}%</td><td class="n">{c["dark_pool_share_pct"]}%</td></tr>'
        for c in confluence
    )
    return (
        '<div class="wrap"><table><tr><th class="n">DP level</th><th>Nearest GEX level</th>'
        '<th class="n">Distance</th><th class="n">Dark-pool share</th></tr>'
        f'{rows}</table></div>'
    )


def _strike_table(top_strikes, source):
    if not top_strikes:
        return '<p class="note">No per-strike gamma data.</p>'

    def money(v):
        return f'<td class="n {"bull" if v >= 0 else "bear"}">{"-" if v < 0 else ""}${abs(v) / 1e6:,.1f}M</td>'

    rows = "".join(
        f'<tr><td class="n">${s.strike:,.2f}</td>{money(s.net(source))}'
        f'{money(s.call_gamma_vol if source == "vol" else s.call_gamma_oi)}'
        f'{money(s.put_gamma_vol if source == "vol" else s.put_gamma_oi)}</tr>'
        for s in top_strikes
    )
    return (
        '<div class="wrap"><table><tr><th class="n">Strike</th><th class="n">Net gamma</th>'
        '<th class="n">Call gamma</th><th class="n">Put gamma</th></tr>'
        f'{rows}</table></div>'
    )


def render_html(ticker, gex, levels, blocks, confluence, bias, block_floor,
                top_strikes=None, strike_source="vol", chart_html=None, banner="", session=None):
    tone = {"bullish": "bull", "bearish": "bear"}.get(bias["net_bias"], "")
    strike_section = (
        f'<section><h2>Top gamma strikes ({escape(strike_source)} basis)</h2>'
        f'{_strike_table(top_strikes, strike_source)}</section>'
        if top_strikes is not None else ""
    )
    session_part = f"session {escape(str(session))} &middot; " if session else ""
    chart_section = (f'<section><h2>Price, dark-pool levels and GEX structure</h2>{chart_html}</section>\n'
                     if chart_html else "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{BRAND} &mdash; {escape(ticker)}</title><style>{_CSS}{CHART_CSS}</style></head>
<body><main>
<p class="brand">{BRAND}</p>
{banner}<h1>{escape(ticker)} &mdash; Dark Pool + GEX Scan</h1>
<p class="sub">{session_part}levels {escape(str(gex.date))} &middot; GEX source: {escape(str(gex.source))} &middot; data: Unusual Whales API</p>

{chart_section}<section><h2>Dark-pool ladder with GEX levels</h2>{_ladder(levels, gex)}</section>
{strike_section}
<section><h2>Level / GEX confluence</h2>{_confluence_table(confluence)}</section>
<section><h2>Block prints (&ge; ${block_floor:,.0f} notional)</h2>{_blocks_table(blocks)}</section>
<section><h2>Options flow bias</h2>
<p><strong class="{tone}">{escape(bias["net_bias"].upper())}</strong> &mdash;
{bias["n"]} alerts, ${bias["bullish_premium"]:,.0f} bullish vs ${bias["bearish_premium"]:,.0f} bearish premium,
{bias["sweep_count"]} sweeps.</p></section>
</main></body></html>
"""
