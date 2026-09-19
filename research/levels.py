"""
Turn one day's UW data into labelled price levels for the NEXT session.

Groups (the claim under test is confluence > either signal alone):
  confluence  heavy dark-pool level within `proximity_pct` of a GEX level
  dp_only     heavy dark-pool level with no GEX level nearby
  gex_only    GEX level with no heavy dark-pool level nearby
  placebo     each confluence level shifted +/- `placebo_shift_pct` (a level
              that means nothing) -- the "does ANY level attract reaction" baseline
"Heavy" = the `top_n` price levels by dark-pool volume that day.
"""
GEX_FIELDS = ("call_wall", "put_wall", "gamma_flip", "gamma_magnet")


def _near(a, b, pct):
    return b != 0 and abs(a - b) / b * 100.0 <= pct


def label_levels(price_levels, gex, top_n=5, proximity_pct=0.5, placebo_shift_pct=0.75):
    heavy = sorted(price_levels.levels, key=lambda lv: lv.dark_pool_volume, reverse=True)[:top_n]
    gex_prices = [getattr(gex, f) for f in GEX_FIELDS if getattr(gex, f) is not None]

    out = []
    for lv in heavy:
        near_gex = any(_near(lv.price, g, proximity_pct) for g in gex_prices)
        out.append({"price": lv.price, "group": "confluence" if near_gex else "dp_only"})
        if near_gex:
            for sign in (1, -1):
                out.append({"price": lv.price * (1 + sign * placebo_shift_pct / 100.0), "group": "placebo"})
    for g in gex_prices:
        if not any(_near(lv.price, g, proximity_pct) for lv in heavy):
            out.append({"price": g, "group": "gex_only"})
    return out
