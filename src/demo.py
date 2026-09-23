"""
Synthetic demo session -- `python main.py demo` renders the full Black Lantern report with no API key.

Every number here is generated (seeded, so the page is identical on every run) in the SAME raw shape the Unusual
Whales API returns, and goes through the real parsers and analysis, so the demo exercises the real code path. It is
labelled as synthetic on the page. Real UW data is never shipped in this repo (the API terms are personal-use only).
"""
import random
from datetime import datetime, timedelta, timezone

from . import analysis
from .models import Candle, DarkPoolPrint, DarkPoolPriceLevels, FlowAlert, GexLevels, StrikeGamma

TICKER = "DEMO"
SESSION = datetime(2026, 9, 18, 13, 30, tzinfo=timezone.utc)      # 09:30 ET
SESSION_DATE = "2026-09-18"
PRIOR_DATE = "2026-09-17"
BANNER = ('<p class="banner">SYNTHETIC DEMO DATA &mdash; generated, not real market data. '
          'Run <code>python main.py scan SPY --html out.html</code> with an Unusual Whales key for a live session.</p>')


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build(seed=7):
    """Returns the parsed models a live scan would produce: candles, levels, gex, prints, strikes, alerts."""
    rng = random.Random(seed)

    # One regular session of 5m candles: a morning drift down into the put-wall / heavy dark-pool zone,
    # a bounce, then a push back up toward the call wall.
    raw_candles, price = [], 101.20
    for i in range(78):
        drift = -0.075 if i < 22 else (0.055 if i < 60 else 0.0)
        o = price
        c = round(o + drift + rng.gauss(0, 0.12), 2)
        h = round(max(o, c) + abs(rng.gauss(0, 0.07)), 2)
        l = round(min(o, c) - abs(rng.gauss(0, 0.07)), 2)
        start = SESSION + timedelta(minutes=5 * i)
        raw_candles.append({"open": o, "high": h, "low": l, "close": c, "volume": rng.randint(80_000, 600_000),
                            "start_time": _iso(start), "end_time": _iso(start + timedelta(minutes=5)),
                            "market_time": "r"})
        price = c
    candles = [Candle.from_api(r) for r in raw_candles]

    # Prior-session dark-pool price levels (the view you would trade from): two heavy clusters plus noise.
    level_rows = []
    for p in (99.80, 99.85, 101.50, 102.60, 100.40, 98.10, 103.40, 100.95, 99.30, 102.05):
        heavy = p in (99.80, 101.50, 102.60)
        dark = rng.randint(1_400_000, 2_600_000) if heavy else rng.randint(150_000, 700_000)
        level_rows.append({"price": f"{p:.2f}", "dark_pool_volume": dark, "regular_volume": rng.randint(300_000, 1_500_000)})
    levels = DarkPoolPriceLevels.from_api(TICKER, {"date": PRIOR_DATE, "data": level_rows})
    gex = GexLevels.from_api(TICKER, {"date": PRIOR_DATE, "source": "vol", "time": "2026-09-17T20:14:00Z",
                                      "call_wall": "102.60", "put_wall": "99.80", "gamma_flip": "100.70",
                                      "gamma_magnet": "101.50", "nearby_flips": ["100.70"]})

    # Dark-pool prints through the session, a few of them large blocks clustered near the heavy levels.
    prints = []
    for k in range(60):
        c = rng.choice(candles)
        when = datetime.fromisoformat(c.start_time.replace("Z", "+00:00")) + timedelta(seconds=rng.randint(0, 299))
        px = round(rng.uniform(c.low, c.high), 2)
        size = rng.choice([800, 1_500, 3_000, 5_000, 12_000, 25_000, 60_000]) if k % 3 == 0 else rng.randint(100, 2_000)
        prints.append(DarkPoolPrint.from_api({
            "ticker": TICKER, "executed_at": _iso(when), "price": f"{px:.2f}", "size": size,
            "premium": f"{px * size:.2f}", "volume": 0, "market_center": "L", "canceled": False,
            "nbbo_bid": f"{px - 0.01:.2f}", "nbbo_ask": f"{px + 0.01:.2f}", "tracking_id": 10_000 + k}))

    strikes = [StrikeGamma.from_api({"strike": f"{s:.2f}", "price": "101.00", "time": "2026-09-17T20:14:00Z",
                                     "call_gamma_oi": str(g * 0.8), "call_gamma_vol": str(g),
                                     "put_gamma_oi": str(-p * 0.8), "put_gamma_vol": str(-p)})
               for s, g, p in ((99.0, 2e7, 9e7), (100.0, 6e7, 1.4e8), (101.0, 1.1e8, 6e7),
                               (102.0, 1.6e8, 3e7), (103.0, 7e7, 1e7))]

    alerts = [FlowAlert.from_api({
        "ticker": TICKER, "created_at": _iso(SESSION + timedelta(minutes=20 * i)), "type": kind,
        "strike": strike, "expiry": "2026-09-25", "price": "1.10", "underlying_price": "100.90",
        "total_premium": prem, "total_ask_side_prem": prem * ask, "total_bid_side_prem": prem * (1 - ask),
        "total_size": 900, "volume": 2_500, "open_interest": 700, "volume_oi_ratio": 3.6,
        "has_sweep": i % 2 == 0, "has_floor": False, "has_multileg": False, "alert_rule": "RepeatedHits",
        "option_chain": None}) for i, (kind, strike, prem, ask) in enumerate(
            (("call", "102", 480_000, 0.8), ("call", "103", 350_000, 0.7), ("put", "99", 210_000, 0.35),
             ("call", "101", 620_000, 0.75), ("put", "100", 150_000, 0.6)))]

    return {"ticker": TICKER, "candles": candles, "levels": levels, "gex": gex, "prints": prints,
            "strikes": strikes, "alerts": alerts, "levels_date": PRIOR_DATE,
            "top_strikes": analysis.top_gamma_strikes(strikes, source="vol", n=5)}
