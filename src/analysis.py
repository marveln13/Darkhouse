"""
First real analytical layer on top of the three raw UW endpoint families.
Nothing here calls the network -- pure functions over already-parsed
models, so they're fully unit-testable against fixtures without a live
API key.
"""

DEFAULT_BLOCK_NOTIONAL_FLOOR = 200_000  # matches ARGUS's own dark-pool block-print floor


def block_prints(prints, notional_floor=DEFAULT_BLOCK_NOTIONAL_FLOOR):
    """Dark pool prints at or above a real notional-$ floor, largest first."""
    blocks = [p for p in prints if not p.canceled and p.notional >= notional_floor]
    return sorted(blocks, key=lambda p: p.notional, reverse=True)


def price_level_confluence(price_levels, gex, proximity_pct=0.5):
    """
    Real dark-pool price levels that sit within `proximity_pct`% of a GEX
    structural level (call wall / put wall / gamma flip / gamma magnet).
    A price level with heavy real dark-pool volume AND a dealer-gamma
    structural level at (near) the same price is a stronger confluence
    read than either signal alone.
    """
    gex_points = {
        "call_wall": gex.call_wall,
        "put_wall": gex.put_wall,
        "gamma_flip": gex.gamma_flip,
        "gamma_magnet": gex.gamma_magnet,
    }
    hits = []
    for level in price_levels.levels:
        for label, gex_price in gex_points.items():
            if gex_price is None or level.price == 0:
                continue
            distance_pct = abs(level.price - gex_price) / level.price * 100.0
            if distance_pct <= proximity_pct:
                hits.append({
                    "price": level.price,
                    "gex_level": label,
                    "gex_price": gex_price,
                    "distance_pct": round(distance_pct, 3),
                    "dark_pool_volume": level.dark_pool_volume,
                    "dark_pool_share_pct": level.dark_pool_share_pct,
                })
    return sorted(hits, key=lambda h: h["distance_pct"])


def flow_bias(alerts):
    """Aggregate real premium tilt across a batch of flow alerts."""
    if not alerts:
        return {"n": 0, "bullish_premium": 0.0, "bearish_premium": 0.0, "net_bias": "flat", "sweep_count": 0}

    bullish_premium = sum(a.total_premium for a in alerts if a.is_bullish_skewed)
    bearish_premium = sum(a.total_premium for a in alerts if not a.is_bullish_skewed)
    total = bullish_premium + bearish_premium
    if total == 0:
        net_bias = "flat"
    else:
        tilt = (bullish_premium - bearish_premium) / total
        net_bias = "bullish" if tilt > 0.1 else "bearish" if tilt < -0.1 else "flat"

    return {
        "n": len(alerts),
        "bullish_premium": round(bullish_premium, 2),
        "bearish_premium": round(bearish_premium, 2),
        "net_bias": net_bias,
        "sweep_count": sum(1 for a in alerts if a.has_sweep),
    }
