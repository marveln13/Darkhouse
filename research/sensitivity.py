"""
Robustness grid for the confluence event study. Every row varies ONE
parameter from the primary configuration; all rows are printed (nothing is
filtered to the best). With ~9 rows and 3 comparisons each, a lone p < 0.05
is expected by chance -- read the table for consistency of sign and size,
not for a single winner.

    python -m research.sensitivity [--tickers SPY,QQQ,NVDA,TSLA] [--days 250]
"""
import argparse
import os
from types import SimpleNamespace

from dotenv import load_dotenv

from src.uw_client import UnusualWhalesClient

from . import reaction
from .bars import load_m30
from .caching_client import CachingClient
from .run import DEFAULT_ROOT, REPO_ROOT, collect_events

PRIMARY = dict(k=0.5, horizon=4, top_n=5, proximity=0.1, gex_source="oi")
GRID = [
    ("primary", {}),
    ("proximity 0.05%", {"proximity": 0.05}),
    ("proximity 0.25%", {"proximity": 0.25}),
    ("reaction 0.25 ATR", {"k": 0.25}),
    ("reaction 1.0 ATR", {"k": 1.0}),
    ("horizon 2 bars", {"horizon": 2}),
    ("horizon 8 bars", {"horizon": 8}),
    ("top-3 dp levels", {"top_n": 3}),
    ("top-8 dp levels", {"top_n": 8}),
    ("gex source = vol", {"gex_source": "vol"}),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--argus-root", default=DEFAULT_ROOT)
    ap.add_argument("--tickers", default="SPY,QQQ,NVDA,TSLA")
    ap.add_argument("--days", type=int, default=250)
    a = ap.parse_args()

    client = CachingClient(UnusualWhalesClient(), os.path.join(REPO_ROOT, ".cache", "uw"))
    bars = {t: load_m30(a.argus_root, t) for t in a.tickers.split(",")}

    print(f"{'config':<20}{'n_conf':>7}{'conf hold':>10}   {'vs dp_only':>18}{'vs gex_only':>18}{'vs placebo':>18}")
    for name, override in GRID:
        args = SimpleNamespace(**{**PRIMARY, **override})
        events = []
        for t, b in bars.items():
            events.extend(collect_events(client, t, b, a.days, args)[0])
        cells = []
        for ctrl in ("dp_only", "gex_only", "placebo"):
            r = reaction.compare_groups(events, "confluence", ctrl)
            cells.append("n/a" if r["t"] is None else f"{100 * (r['hold_a'] - r['hold_b']):+.1f}pt t={r['t']:+.2f}")
        r0 = reaction.compare_groups(events, "confluence", "dp_only")
        hold = "n/a" if r0["hold_a"] is None else f"{100 * r0['hold_a']:.1f}%"
        print(f"{name:<20}{r0['n_a']:>7}{hold:>10}   {cells[0]:>18}{cells[1]:>18}{cells[2]:>18}")


if __name__ == "__main__":
    load_dotenv()
    main()
