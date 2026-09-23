"""
The Black Lantern chart: one session's candles with the dark-pool levels, the GEX structure and the block prints drawn
on top, so "where did big money trade" and "where do dealers have to hedge" are visible against price in one picture.

Pure functions, no network: `build_chart` turns parsed models into a plain dict of drawable items (unit-testable as
data), `render_chart_svg` turns that dict into self-contained inline SVG plus a few lines of vanilla JS for a
crosshair readout. No external assets, so the HTML report still works offline.
"""
import bisect
import json
import math
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

GEX_LABELS = {"call_wall": "Call wall", "put_wall": "Put wall", "gamma_flip": "Gamma flip", "gamma_magnet": "Gamma magnet"}
TOP_N_DARK_POOL = 5          # same "heavy level" selection as research/levels.py
MIN_REACH_PCT = 0.25         # a level is drawn if it lies within one session range (at least this % of price)
                             # beyond the session high/low; farther levels go in the margin note, not on the chart
BLOCK_R_MIN, BLOCK_R_MAX = 3.0, 14.0


def _ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def heavy_levels(price_levels, top_n=TOP_N_DARK_POOL):
    """The top_n dark-pool price levels by dark-pool volume, heaviest first."""
    return sorted(price_levels.levels, key=lambda lv: lv.dark_pool_volume, reverse=True)[:top_n]


def block_x(starts, ends, when):
    """Fractional candle index of a timestamp (candle i spans [i, i+1)), or None outside the candles."""
    if not starts or when < starts[0] or when >= ends[-1]:
        return None
    i = bisect.bisect_right(starts, when) - 1
    span = (ends[i] - starts[i]).total_seconds()
    frac = (when - starts[i]).total_seconds() / span if span > 0 else 0.0
    return i + min(max(frac, 0.0), 1.0)


def block_radius(notional, max_notional):
    """Circle AREA proportional to notional, clamped to [BLOCK_R_MIN, BLOCK_R_MAX]."""
    if max_notional <= 0:
        return BLOCK_R_MIN
    return BLOCK_R_MIN + (BLOCK_R_MAX - BLOCK_R_MIN) * math.sqrt(max(notional, 0) / max_notional)


def build_chart(candles, price_levels, gex, blocks, confluence, levels_date=None, levels_note="",
                top_n=TOP_N_DARK_POOL, blocks_note=""):
    """Everything the renderer draws, as plain data. Returns None when there are no candles."""
    if not candles:
        return None
    lo, hi = min(c.low for c in candles), max(c.high for c in candles)
    reach = max(hi - lo, (hi + lo) / 2 * MIN_REACH_PCT / 100)
    reach_lo, reach_hi = lo - reach, hi + reach
    confluent = {round(c["price"], 4) for c in confluence}

    heavy = heavy_levels(price_levels, top_n) if price_levels else []
    max_vol = max((lv.dark_pool_volume for lv in heavy), default=0) or 1
    dp, gex_lines, offscreen = [], [], []
    for lv in heavy:
        item = {"price": lv.price, "volume": lv.dark_pool_volume, "share_pct": lv.dark_pool_share_pct,
                "weight": lv.dark_pool_volume / max_vol, "confluence": round(lv.price, 4) in confluent}
        (dp if reach_lo <= lv.price <= reach_hi else offscreen).append(dict(item, label="Dark-pool level"))
    for key, label in GEX_LABELS.items():
        price = getattr(gex, key, None) if gex else None
        if price is None:
            continue
        (gex_lines if reach_lo <= price <= reach_hi else offscreen).append({"key": key, "label": label, "price": price})

    drawn = [x["price"] for x in dp + gex_lines]
    y_min, y_max = min([lo] + drawn), max([hi] + drawn)
    pad = (y_max - y_min) * 0.04 or y_max * 0.001
    starts = [_ts(c.start_time) for c in candles]
    ends = [_ts(c.end_time) for c in candles]

    shown = []
    for b in blocks:
        x = block_x(starts, ends, _ts(b.executed_at))
        if x is not None:
            shown.append((x, b))
    max_notional = max((b.notional for _, b in shown), default=0)
    marks = [{"x": x, "price": b.price, "size": b.size, "notional": b.notional, "time": b.executed_at,
              "r": block_radius(b.notional, max_notional)} for x, b in shown]

    return {
        "candles": [{"t": c.start_time, "o": c.open, "h": c.high, "l": c.low, "c": c.close} for c in candles],
        "y_min": y_min - pad, "y_max": y_max + pad,
        "dark_pool": dp, "gex": gex_lines, "offscreen": sorted(offscreen, key=lambda o: -o["price"]),
        "blocks": sorted(marks, key=lambda m: -m["r"]),          # big circles first so small ones stay on top
        "blocks_outside": len(blocks) - len(shown),
        "levels_date": levels_date, "levels_note": levels_note, "blocks_note": blocks_note,
    }


def _et_clock(ts):
    return _ts(ts).astimezone(ET).strftime("%H:%M")


def _spread_labels(items, min_gap):
    """Nudge label y positions (sorted top to bottom) so no two are closer than min_gap."""
    placed = []
    for y, text, cls in sorted(items):
        if placed and y - placed[-1][0] < min_gap:
            y = placed[-1][0] + min_gap
        placed.append((y, text, cls))
    return placed


def render_chart_svg(chart, width=960, height=440):
    if chart is None:
        return '<p class="note">No candle data for this session.</p>'
    left, right, top, bottom = 58, 176, 14, 28
    pw, ph = width - left - right, height - top - bottom
    n = len(chart["candles"])
    slot = pw / n
    y0, y1 = chart["y_min"], chart["y_max"]

    def x_at(i):
        return left + i * slot

    def y_at(p):
        return top + (y1 - p) / (y1 - y0) * ph

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Price with dark-pool and GEX levels" '
             f'class="bl-chart" preserveAspectRatio="xMidYMid meet">']

    for k in range(6):                                                   # price grid + axis labels
        p = y0 + (y1 - y0) * k / 5
        y = y_at(p)
        parts.append(f'<line class="grid" x1="{left}" x2="{left + pw}" y1="{y:.1f}" y2="{y:.1f}"/>'
                     f'<text class="axis" x="{left - 6}" y="{y + 4:.1f}" text-anchor="end">{p:,.2f}</text>')
    step = max(1, round(n / 8))
    for i in range(0, n, step):                                          # time axis (ET)
        parts.append(f'<text class="axis" x="{x_at(i + 0.5):.1f}" y="{height - 8}" text-anchor="middle">'
                     f'{_et_clock(chart["candles"][i]["t"])}</text>')

    labels = []
    for lv in chart["dark_pool"]:
        y = y_at(lv["price"])
        h = 2 + 7 * lv["weight"]
        cls = "dp conf" if lv["confluence"] else "dp"
        tip = (f'{"Confluence: " if lv["confluence"] else ""}dark-pool level ${lv["price"]:,.2f} -- '
               f'{lv["volume"]:,} shares ({lv["share_pct"]}% dark)')
        parts.append(f'<rect class="{cls}" x="{left}" y="{y - h / 2:.1f}" width="{pw}" height="{h:.1f}">'
                     f'<title>{escape(tip)}</title></rect>')
        labels.append((y, f'DP ${lv["price"]:,.2f}{" *" if lv["confluence"] else ""}', cls))
    for g in chart["gex"]:
        y = y_at(g["price"])
        parts.append(f'<line class="gex {escape(g["key"])}" x1="{left}" x2="{left + pw}" y1="{y:.1f}" y2="{y:.1f}">'
                     f'<title>{escape(g["label"])} ${g["price"]:,.2f}</title></line>')
        labels.append((y, f'{g["label"]} ${g["price"]:,.2f}', f'gexlabel {g["key"]}'))

    for i, c in enumerate(chart["candles"]):                             # candles
        cx = x_at(i + 0.5)
        bw = max(1.0, slot * 0.64)
        cls = "up" if c["c"] >= c["o"] else "down"
        yo, yc = y_at(c["o"]), y_at(c["c"])
        parts.append(f'<line class="wick {cls}" x1="{cx:.1f}" x2="{cx:.1f}" y1="{y_at(c["h"]):.1f}" y2="{y_at(c["l"]):.1f}"/>'
                     f'<rect class="body {cls}" x="{cx - bw / 2:.1f}" y="{min(yo, yc):.1f}" width="{bw:.1f}" '
                     f'height="{max(abs(yc - yo), 1):.1f}"/>')

    for b in chart["blocks"]:                                            # block prints
        tip = f'Block print {b["size"]:,} @ ${b["price"]:,.2f} = ${b["notional"]:,.0f} at {_et_clock(b["time"])} ET'
        parts.append(f'<circle class="block" cx="{x_at(b["x"]):.1f}" cy="{y_at(b["price"]):.1f}" r="{b["r"]:.1f}">'
                     f'<title>{escape(tip)}</title></circle>')

    for y, text, cls in _spread_labels(labels, 13):                      # right-margin labels
        parts.append(f'<text class="lbl {cls}" x="{left + pw + 8}" y="{y + 4:.1f}">{escape(text)}</text>')

    parts.append(f'<line class="xhair" x1="0" x2="0" y1="{top}" y2="{top + ph}" visibility="hidden"/>')
    parts.append("</svg>")

    data = json.dumps({"left": left, "slot": slot, "width": width,
                       "c": [[_et_clock(c["t"]), c["o"], c["h"], c["l"], c["c"]] for c in chart["candles"]]})
    script = ("<script>(function(){var d=" + data.replace("</", "<\\/") + ";"
              "var w=document.currentScript.parentNode,s=w.querySelector('svg'),x=s.querySelector('.xhair'),"
              "o=w.querySelector('.readout');"
              "s.addEventListener('mousemove',function(e){var r=s.getBoundingClientRect(),"
              "px=(e.clientX-r.left)*d.width/r.width,i=Math.floor((px-d.left)/d.slot);"
              "if(i<0||i>=d.c.length){x.setAttribute('visibility','hidden');return;}"
              "var k=d.c[i],cx=d.left+(i+0.5)*d.slot;x.setAttribute('x1',cx);x.setAttribute('x2',cx);"
              "x.setAttribute('visibility','visible');"
              "o.textContent=k[0]+' ET  O '+k[1].toFixed(2)+'  H '+k[2].toFixed(2)+'  L '+k[3].toFixed(2)+'  C '+k[4].toFixed(2);});"
              "s.addEventListener('mouseleave',function(){x.setAttribute('visibility','hidden');o.textContent='';});"
              "})();</script>")

    notes = []
    if chart["levels_date"]:
        notes.append(f'Levels from {escape(str(chart["levels_date"]))}{escape(chart["levels_note"])}.')
    if chart["offscreen"]:
        notes.append("Off-chart levels: " + ", ".join(
            f'{escape(o["label"])} ${o["price"]:,.2f}' for o in chart["offscreen"]) + ".")
    if chart.get("blocks_note"):
        notes.append(escape(chart["blocks_note"]))
    if chart["blocks_outside"]:
        notes.append(f'{chart["blocks_outside"]} block print(s) outside regular-session candles not drawn.')
    legend = ('<div class="legend"><span><i class="sw dpsw"></i>Dark-pool level (thicker = more volume)</span>'
              '<span><i class="sw confsw"></i>Dark-pool level within 0.1% of a GEX level (*)</span>'
              '<span><i class="sw gexsw"></i>GEX wall / flip / magnet</span>'
              '<span><i class="sw blocksw"></i>Block print (area = $ notional)</span></div>')
    return (f'<div class="chartwrap">{legend}<div class="readout" aria-live="polite"></div>{"".join(parts)}'
            f'<p class="note">{" ".join(notes)}</p>{script}</div>')


CHART_CSS = """
:root{--up:#15803d;--down:#b91c1c;--dp:#3b6fd4;--conf:#7c3aed;--blk:#d97706;--grid:#e6e9ef}
@media (prefers-color-scheme:dark){:root{--up:#4ade80;--down:#f87171;--dp:#6b9bf5;--conf:#c084fc;--blk:#fbbf24;--grid:#252b35}}
.chartwrap{position:relative;overflow-x:auto}
.bl-chart{width:100%;min-width:680px;height:auto;display:block;font:11px system-ui,sans-serif}
.bl-chart .grid{stroke:var(--grid);stroke-width:1}
.bl-chart .axis{fill:var(--muted)}
.bl-chart .wick{stroke-width:1}.bl-chart .wick.up{stroke:var(--up)}.bl-chart .wick.down{stroke:var(--down)}
.bl-chart .body.up{fill:var(--up)}.bl-chart .body.down{fill:var(--down)}
.bl-chart .dp{fill:var(--dp);opacity:.28}.bl-chart .dp.conf{fill:var(--conf);opacity:.45}
.bl-chart .gex{stroke:var(--gex);stroke-width:1.5;stroke-dasharray:6 4}
.bl-chart .gex.gamma_flip{stroke-dasharray:2 3;stroke-width:2}
.bl-chart .block{fill:var(--blk);fill-opacity:.35;stroke:var(--blk);stroke-width:1.2}
.bl-chart .lbl{fill:var(--ink);font-size:11px}
.bl-chart .lbl.dp{fill:var(--dp);opacity:1}.bl-chart .lbl.conf{fill:var(--conf)}
.bl-chart .gexlabel{fill:var(--gex)}
.bl-chart .xhair{stroke:var(--muted);stroke-width:1;stroke-dasharray:3 3}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;color:var(--muted);margin-bottom:6px}
.sw{display:inline-block;width:14px;height:8px;margin-right:6px;vertical-align:middle;border-radius:2px}
.dpsw{background:var(--dp);opacity:.5}.confsw{background:var(--conf);opacity:.7}
.gexsw{border-top:2px dashed var(--gex);height:0}.blocksw{background:var(--blk);opacity:.6;border-radius:50%;width:10px;height:10px}
.readout{min-height:20px;font:13px ui-monospace,monospace;color:var(--muted)}
"""

# Tokens the chart CSS reads from the report page; repeated here so a standalone SVG file renders on its own.
_STANDALONE_TOKENS = """
svg{--ink:#14181f;--muted:#5d6675;--gex:#c2410c;background:#fff}
@media (prefers-color-scheme:dark){svg{--ink:#e8ebf0;--muted:#98a2b3;--gex:#fb923c;background:#171b22}}
"""


def standalone_svg(chart, width=960, height=440):
    """The chart as a self-contained .svg file (for a README image): same drawing, styles embedded, no script."""
    html = render_chart_svg(chart, width, height)
    start, end = html.index("<svg"), html.index("</svg>") + len("</svg>")
    svg = html[start:end].replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
    style = (CHART_CSS.replace(":root", "svg") + _STANDALONE_TOKENS).replace(".bl-chart ", "")
    return svg.replace(">", f"><style>{style}</style>", 1)
