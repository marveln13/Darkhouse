"""
Parsed shapes for the three UW endpoint families this project uses.
Field names follow the real documented API responses (see README) --
/api/darkpool/recent and /api/darkpool/{ticker} return some numeric
fields as decimal strings depending on endpoint, so every numeric field
here goes through _num() rather than assuming a type.
"""
from dataclasses import dataclass, field
from typing import Optional


def _num(value):
    if value is None:
        return None
    return float(value)


@dataclass
class DarkPoolPrint:
    ticker: str
    executed_at: str
    price: float
    size: int
    premium: float
    volume: int
    market_center: str
    canceled: bool
    nbbo_bid: Optional[float]
    nbbo_ask: Optional[float]
    tracking_id: int

    @property
    def notional(self):
        return self.price * self.size

    @classmethod
    def from_api(cls, raw):
        return cls(
            ticker=raw["ticker"],
            executed_at=raw["executed_at"],
            price=_num(raw["price"]),
            size=int(raw["size"]),
            premium=_num(raw["premium"]),
            volume=int(raw["volume"]),
            market_center=raw.get("market_center", ""),
            canceled=bool(raw.get("canceled", False)),
            nbbo_bid=_num(raw.get("nbbo_bid")),
            nbbo_ask=_num(raw.get("nbbo_ask")),
            tracking_id=int(raw["tracking_id"]),
        )


@dataclass
class DarkPoolPriceLevel:
    price: float
    dark_pool_volume: int
    regular_volume: int

    @property
    def dark_pool_share_pct(self):
        total = self.dark_pool_volume + self.regular_volume
        return round(100.0 * self.dark_pool_volume / total, 1) if total else 0.0

    @classmethod
    def from_api(cls, raw):
        return cls(
            price=_num(raw["price"]),
            dark_pool_volume=int(raw["dark_pool_volume"]),
            regular_volume=int(raw["regular_volume"]),
        )


@dataclass
class DarkPoolPriceLevels:
    ticker: str
    date: str
    levels: list = field(default_factory=list)

    @classmethod
    def from_api(cls, ticker, raw):
        return cls(
            ticker=ticker,
            date=raw["date"],
            levels=[DarkPoolPriceLevel.from_api(r) for r in raw.get("data", [])],
        )


@dataclass
class GexLevels:
    ticker: str
    date: str
    source: str
    time: str
    call_wall: Optional[float]
    put_wall: Optional[float]
    gamma_flip: Optional[float]
    gamma_magnet: Optional[float]
    nearby_flips: list = field(default_factory=list)

    @classmethod
    def from_api(cls, ticker, raw):
        return cls(
            ticker=ticker,
            date=raw.get("date"),
            source=raw.get("source"),
            time=raw.get("time"),
            call_wall=_num(raw.get("call_wall")),
            put_wall=_num(raw.get("put_wall")),
            gamma_flip=_num(raw.get("gamma_flip")),
            gamma_magnet=_num(raw.get("gamma_magnet")),
            nearby_flips=[_num(v) for v in raw.get("nearby_flips", []) or []],
        )


@dataclass
class FlowAlert:
    ticker: str
    created_at: str
    type: str
    strike: float
    expiry: str
    price: float
    underlying_price: float
    total_premium: float
    total_ask_side_prem: float
    total_bid_side_prem: float
    total_size: int
    volume: int
    open_interest: int
    volume_oi_ratio: Optional[float]
    has_sweep: bool
    has_floor: bool
    has_multileg: bool
    alert_rule: str

    @property
    def is_bullish_skewed(self):
        """Ask-side buying on a call, or bid-side selling on a put --
        both real, standard 'aggressive bullish premium' reads."""
        if self.type == "call":
            return self.total_ask_side_prem > self.total_bid_side_prem
        if self.type == "put":
            return self.total_bid_side_prem > self.total_ask_side_prem
        return False

    @classmethod
    def from_api(cls, raw):
        return cls(
            ticker=raw["ticker"],
            created_at=raw["created_at"],
            type=raw["type"],
            strike=_num(raw["strike"]),
            expiry=raw["expiry"],
            price=_num(raw["price"]),
            underlying_price=_num(raw["underlying_price"]),
            total_premium=_num(raw["total_premium"]),
            total_ask_side_prem=_num(raw["total_ask_side_prem"]),
            total_bid_side_prem=_num(raw["total_bid_side_prem"]),
            total_size=int(raw["total_size"]),
            volume=int(raw["volume"]),
            open_interest=int(raw["open_interest"]),
            volume_oi_ratio=_num(raw.get("volume_oi_ratio")),
            has_sweep=bool(raw.get("has_sweep", False)),
            has_floor=bool(raw.get("has_floor", False)),
            has_multileg=bool(raw.get("has_multileg", False)),
            alert_rule=raw.get("alert_rule", ""),
        )
