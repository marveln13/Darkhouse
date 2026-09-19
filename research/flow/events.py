"""
Roll UW flow alerts up to one EVENT per (ticker, contract, ET day): the unit a
human flow trader actually reasons about ("$4M in the 10/02 355 calls today,
mostly ask-side, 16x open interest").
"""
import re
from dataclasses import dataclass
from datetime import date as date_cls, datetime

from compare.argus_logs import ET


def _dt(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


@dataclass
class EodStats:
    """One contract's end-of-day stats from /api/option-contract/{id}/historic.
    Verified against the leader's screenshot for GOOGL 10/02 $355C on 2026-09-10
    (open_interest is the START-of-day figure; next day's jumped 900 -> 15,263)."""
    volume: int
    open_interest: int
    ask_volume: int
    bid_volume: int
    floor_volume: int
    multi_leg_volume: int
    total_premium: float
    open_price: float
    high_price: float
    low_price: float
    last_price: float
    avg_price: float

    @property
    def vol_oi(self):
        return self.volume / self.open_interest if self.open_interest else None

    @property
    def ask_share(self):
        sided = self.ask_volume + self.bid_volume
        return self.ask_volume / sided if sided else None

    @property
    def floor_share(self):
        return self.floor_volume / self.volume if self.volume else 0.0

    @property
    def multileg_share(self):
        return self.multi_leg_volume / self.volume if self.volume else 0.0

    @classmethod
    def from_row(cls, row):
        f = lambda k: float(row[k]) if row.get(k) is not None else 0.0
        i = lambda k: int(row[k]) if row.get(k) is not None else 0
        return cls(volume=i("volume"), open_interest=i("open_interest"), ask_volume=i("ask_volume"),
                   bid_volume=i("bid_volume"), floor_volume=i("floor_volume"),
                   multi_leg_volume=i("multi_leg_volume"), total_premium=f("total_premium"),
                   open_price=f("open_price"), high_price=f("high_price"), low_price=f("low_price"),
                   last_price=f("last_price"), avg_price=f("avg_price"))


@dataclass
class FlowEvent:
    ticker: str
    chain: str
    date: str
    type: str
    strike: float
    expiry: str
    dte: int
    n_alerts: int
    cum_premium: float
    ask_prem: float
    bid_prem: float
    max_vol_oi: float
    open_interest: int
    sweeps: int
    floors: int
    multileg: bool
    first_ts: str
    first_price: float
    underlying_price: float
    eod: "EodStats | None" = None

    @property
    def otm_pct(self):
        """Positive = out of the money, for either calls or puts."""
        gap = self.strike - self.underlying_price if self.type == "call" else self.underlying_price - self.strike
        return gap / self.underlying_price * 100.0


def aggregate_events(alerts):
    groups = {}
    for a in alerts:
        if not a.option_chain:
            continue
        day = _dt(a.created_at).astimezone(ET).date().isoformat()
        groups.setdefault((a.ticker, a.option_chain, day), []).append(a)

    events = []
    for (ticker, chain, day), rows in groups.items():
        rows.sort(key=lambda a: a.created_at)
        first = rows[0]
        dte = (date_cls.fromisoformat(first.expiry) - date_cls.fromisoformat(day)).days
        events.append(FlowEvent(
            ticker=ticker, chain=chain, date=day, type=first.type, strike=first.strike,
            expiry=first.expiry, dte=dte, n_alerts=len(rows),
            cum_premium=sum(a.total_premium for a in rows),
            ask_prem=sum(a.total_ask_side_prem for a in rows),
            bid_prem=sum(a.total_bid_side_prem for a in rows),
            max_vol_oi=max((a.volume_oi_ratio or 0.0) for a in rows),
            open_interest=first.open_interest,
            sweeps=sum(1 for a in rows if a.has_sweep), floors=sum(1 for a in rows if a.has_floor),
            multileg=any(a.has_multileg for a in rows),
            first_ts=first.created_at, first_price=first.price, underlying_price=first.underlying_price,
        ))
    return events


_OSI = re.compile(r"^([A-Z.]{1,6})(\d{6})([CP])(\d{8})$")


def parse_osi(chain):
    """'GOOGL261002C00355000' -> ('GOOGL', date(2026,10,2), 'call', 355.0)."""
    m = _OSI.match(chain)
    if not m:
        raise ValueError(f"not an OSI option symbol: {chain!r}")
    root, yymmdd, cp, strike = m.groups()
    expiry = date_cls(2000 + int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:]))
    return root, expiry, "call" if cp == "C" else "put", int(strike) / 1000.0


def event_from_contract_day(chain, day, row, underlying_price):
    """A scoreable event straight from a contract's end-of-day row (no alert history needed)."""
    ticker, expiry, kind, strike = parse_osi(chain)
    eod = EodStats.from_row(row)
    return FlowEvent(
        ticker=ticker, chain=chain, date=day, type=kind, strike=strike, expiry=expiry.isoformat(),
        dte=(expiry - date_cls.fromisoformat(day)).days, n_alerts=0, cum_premium=eod.total_premium,
        ask_prem=0.0, bid_prem=0.0, max_vol_oi=eod.vol_oi or 0.0, open_interest=eod.open_interest,
        sweeps=0, floors=0, multileg=eod.multileg_share >= 0.20, first_ts="", first_price=eod.last_price,
        underlying_price=underlying_price, eod=eod)
