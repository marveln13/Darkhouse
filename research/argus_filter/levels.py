"""
Level definitions for the ARGUS-filter study (PREREGISTRATION.md, "Levels" and "Hypotheses").

For a signal on session D the levels come ONLY from UW data of the prior trading session D-1: the top-N
dark-pool price levels by volume (same selection as research/levels.py) plus the GEX fields call_wall,
put_wall, gamma_flip, gamma_magnet. The request helpers here are the single source of the (path, params)
pairs, so the fetch script and the analysis always hit the same cache key.
"""
import numpy as np

from research.argus_filter import protocol
from research.levels import GEX_FIELDS
from src.models import DarkPoolPriceLevels, GexLevels


def dp_request(ticker, d):
    return f"/api/darkpool/{ticker}/price-levels", {"date": d}


def gex_request(ticker, d):
    return f"/api/stock/{ticker}/gex-levels", {"source": protocol.GEX_SOURCE, "date": d}


def requests_for(ticker, d):
    return (("dp", *dp_request(ticker, d)), ("gex", *gex_request(ticker, d)))


def heavy_prices(price_levels, top_n=protocol.TOP_N_DARKPOOL):
    """Same selection as research.levels.label_levels: top_n by dark-pool volume."""
    heavy = sorted(price_levels.levels, key=lambda lv: lv.dark_pool_volume, reverse=True)[:top_n]
    return [lv.price for lv in heavy]


def parse_dp(ticker, raw):
    """Dark-pool price levels from a cached response, or None when the day has no usable data."""
    if raw is None:
        return None
    levels = DarkPoolPriceLevels.from_api(ticker, raw)
    return levels if levels.levels else None


def parse_gex(ticker, raw):
    """GEX levels from a cached response, or None when the snapshot carries none of the four fields.
    Individual null fields (e.g. no gamma flip that day) are kept as None: the day still counts as present."""
    if raw is None:
        return None
    gex = GexLevels.from_api(ticker, raw.get("data", raw))
    return gex if any(getattr(gex, f) is not None for f in GEX_FIELDS) else None


class DayLevels:
    """One (ticker, D-1)'s levels: `dp` = heavy dark-pool prices, `gex` = {field: price or None}."""

    def __init__(self, dp, gex):
        self.dp = list(dp)
        self.gex = dict(gex)

    @classmethod
    def from_responses(cls, ticker, dp_raw, gex_raw):
        """None when either half is missing -- the caller counts and excludes such a signal."""
        dp, gx = parse_dp(ticker, dp_raw), parse_gex(ticker, gex_raw)
        if dp is None or gx is None:
            return None
        return cls(heavy_prices(dp), {f: getattr(gx, f) for f in GEX_FIELDS})

    @property
    def all_prices(self):
        return self.dp + [v for f, v in self.gex.items() if v is not None]

    @property
    def gamma_flip(self):
        return self.gex.get("gamma_flip")

    def shifted(self, rng):
        """Placebo: every level moved by U(lo, hi) of its own price in a random direction. Draws happen in a
        fixed order (dark-pool levels, then the GEX fields in GEX_FIELDS order; absent fields draw nothing)."""
        def move(p):
            amount = rng.uniform(*protocol.PLACEBO_SHIFT)
            return p * (1 + (amount if rng.random() < 0.5 else -amount))
        return DayLevels([move(p) for p in self.dp],
                         {f: (None if self.gex[f] is None else move(self.gex[f])) for f in GEX_FIELDS})


def placebo_rng(seed=protocol.PLACEBO_SEED):
    return np.random.default_rng(seed)


def has_obstacle(entry, target, prices):
    """H1 rule, exactly as registered: at least one level with target <= level < entry."""
    return any(target <= p < entry for p in prices)


def below_gamma_flip(entry, flip):
    """H2 grouping: True below the flip (negative-gamma zone), False above, None if there is no flip or the
    entry sits exactly on it (neither group)."""
    if flip is None or entry == flip:
        return None
    return entry < flip
