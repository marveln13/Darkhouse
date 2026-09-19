from research.flow import collect, protocol
from research.flow.events import FlowEvent


def _raw(created_at, chain="AAA261002C00100000", premium=100_000, size=100):
    return {"ticker": chain[:3], "created_at": created_at, "type": "call", "strike": "100", "expiry": "2026-10-02",
            "price": "1.0", "underlying_price": "95", "total_premium": str(premium), "total_ask_side_prem": str(premium),
            "total_bid_side_prem": "0", "total_size": size, "volume": 10, "open_interest": 5, "volume_oi_ratio": "2",
            "has_sweep": False, "has_floor": False, "has_multileg": False, "alert_rule": "RepeatedHits",
            "option_chain": chain}


class StreamClient:
    """Newest-first alert stream that honours older_than but IGNORES newer_than, like the real API."""

    def __init__(self, rows):
        self.rows = sorted(rows, key=lambda r: r["created_at"], reverse=True)
        self.calls = 0

    def get(self, path, params=None):
        self.calls += 1
        cutoff = params["older_than"]
        if cutoff.endswith("Z"):
            rows = [r for r in self.rows if r["created_at"] < cutoff]
        else:                                    # an ET-offset ISO string: compare by instant
            from datetime import datetime
            limit = datetime.fromisoformat(cutoff)
            rows = [r for r in self.rows if datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")) < limit]
        return {"data": rows[: params["limit"]]}


def test_discover_day_stops_at_the_day_boundary_instead_of_walking_into_earlier_days():
    day = [_raw(f"2026-09-10T14:{m:02d}:00Z", size=m) for m in range(30)]
    earlier = [_raw(f"2026-09-09T14:{m:02d}:00Z", size=100 + m) for m in range(30)]
    client = StreamClient(day + earlier)

    out = collect.discover_day(client, "2026-09-10", page_limit=10, filters={})

    assert len(out) == 30 and {r["created_at"][:10] for r in out} == {"2026-09-10"}
    assert client.calls <= 4          # 3 full pages of the day, then at most one page that crosses into 9/09


def test_discover_day_dedupes_repeated_rows():
    r = _raw("2026-09-10T14:00:00Z")
    out = collect.discover_day(StreamClient([r, dict(r)]), "2026-09-10", page_limit=10, filters={})
    assert len(out) == 1


def test_weekdays_skips_weekends():
    assert list(collect.weekdays("2026-09-11", "2026-09-15")) == ["2026-09-11", "2026-09-14", "2026-09-15"]


def _event(prem, chain="AAA1", day="2026-09-10"):
    return FlowEvent(ticker="AAA", chain=chain, date=day, type="call", strike=100, expiry="2026-10-02", dte=22,
                     n_alerts=1, cum_premium=prem, ask_prem=prem, bid_prem=0, max_vol_oi=1, open_interest=1,
                     sweeps=0, floors=0, multileg=False, first_ts="", first_price=1, underlying_price=95)


def test_enrichment_targets_keep_the_cutoff_and_sample_the_rest_reproducibly():
    events = [_event(protocol.ENRICH_MIN_ALERT_PREMIUM, chain=f"big{i}") for i in range(5)] + \
             [_event(1_000, chain=f"small{i}") for i in range(2000)]

    keep, sample = collect.enrichment_targets(events)
    again = collect.enrichment_targets(events)

    assert len(keep) == 5
    assert 60 <= len(sample) <= 140                                    # ~5% of 2,000
    assert [e.chain for e in sample] == [e.chain for e in again[1]]    # seeded: same slice every run
    assert not any(e.cum_premium >= protocol.ENRICH_MIN_ALERT_PREMIUM for e in sample)
