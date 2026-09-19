"""
First live-call check: hits each endpoint once and reports the things the
docs left open, so they are settled in one run instead of discovered as bugs.

    python -m scripts.first_call_check [TICKER]

Answers: how list responses are wrapped; whether dark-pool `premium` is
price x size; whether put gamma is signed negative (per-strike and daily);
how many strike rows come back vs the 500 page cap; and what each
greek-exposure `timeframe` value actually returns. Prints only -- nothing is
saved. Never prints the API key.
"""
import statistics
import sys

import requests
from dotenv import load_dotenv

from src.uw_client import UnusualWhalesClient

TIMEFRAMES = (None, "YTD", "1M", "1Y", "2Y")


def shape(obj):
    if isinstance(obj, dict):
        return "dict{" + ", ".join(f"{k}:{type(v).__name__}" for k, v in list(obj.items())[:12]) + "}"
    if isinstance(obj, list):
        return f"list[{len(obj)}] of {shape(obj[0]) if obj else 'empty'}"
    return type(obj).__name__


def rows_of(raw):
    return raw["data"] if isinstance(raw, dict) and "data" in raw else raw


def negative_share(values):
    values = [v for v in values if v is not None]
    return "n/a" if not values else f"{100 * sum(1 for v in values if v < 0) / len(values):.0f}% of {len(values)} negative"


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def check(name, fn):
    print(f"\n=== {name}")
    try:
        fn()
    except requests.HTTPError as e:
        print(f"  HTTP {e.response.status_code}: {e.response.text[:200]!r}")
    except Exception as e:  # keep going -- one bad endpoint shouldn't hide the rest
        print(f"  FAILED: {type(e).__name__}: {e}")


def main(client, ticker):
    def recent():
        raw = client.get("/api/darkpool/recent", {"limit": 3})
        print("  top-level:", shape(raw))
        for r in rows_of(raw)[:3]:
            price, size, prem = fnum(r.get("price")), fnum(r.get("size")), fnum(r.get("premium"))
            print(f"  {r.get('ticker')} price={price} size={size} premium={prem} price*size={price * size if price and size else None}")

    def tprints():
        raw = client.get(f"/api/darkpool/{ticker}", {"limit": 3})
        print("  top-level:", shape(raw))
        print("  fields:", sorted(rows_of(raw)[0]) if rows_of(raw) else "no rows")

    def levels():
        raw = client.get(f"/api/darkpool/{ticker}/price-levels")
        print("  top-level:", shape(raw))

    def gexlv():
        raw = client.get(f"/api/stock/{ticker}/gex-levels", {"source": "oi"})
        print("  ", raw)

    def strikes():
        raw = client.get(f"/api/stock/{ticker}/spot-exposures/strike", {"limit": 500})
        rows = rows_of(raw)
        print(f"  top-level: {shape(raw)}\n  rows returned: {len(rows)} (page cap 500)")
        print("  put_gamma_oi :", negative_share([fnum(r.get("put_gamma_oi")) for r in rows]))
        print("  put_gamma_vol:", negative_share([fnum(r.get("put_gamma_vol")) for r in rows]))
        print("  call_gamma_oi:", negative_share([fnum(r.get("call_gamma_oi")) for r in rows]))

    def greeks():
        for tf in TIMEFRAMES:
            try:
                raw = client.get(f"/api/stock/{ticker}/greek-exposure", {"timeframe": tf} if tf else {})
            except requests.HTTPError as e:
                print(f"  timeframe={tf!s:<6} HTTP {e.response.status_code}")
                continue
            rows = rows_of(raw)
            dates = sorted(r["date"] for r in rows) if rows else []
            print(f"  timeframe={tf!s:<6} rows={len(rows):>4}  {dates[0] if dates else '-'} .. {dates[-1] if dates else '-'}"
                  f"   put_gamma: {negative_share([fnum(r.get('put_gamma')) for r in rows])}")

    def alerts():
        raw = client.get("/api/option-trades/flow-alerts", {"limit": 3, "ticker_symbol": ticker})
        print("  top-level:", shape(raw))

    check("darkpool/recent  (premium semantics, wrapping)", recent)
    check(f"darkpool/{ticker}", tprints)
    check(f"darkpool/{ticker}/price-levels", levels)
    check(f"{ticker} gex-levels", gexlv)
    check(f"{ticker} spot-exposures/strike  (put-gamma sign, page cap)", strikes)
    check(f"{ticker} greek-exposure  (put-gamma sign, timeframe semantics)", greeks)
    check("flow-alerts", alerts)


if __name__ == "__main__":
    load_dotenv()
    main(UnusualWhalesClient(), sys.argv[1] if len(sys.argv) > 1 else "SPY")
