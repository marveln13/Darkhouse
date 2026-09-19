import json
from datetime import datetime, timezone
from types import SimpleNamespace

from compare import argus_logs, dark_pool_match, flow_agreement, gex_agreement, uw_fetch
from src.models import DailyGreekExposure, DarkPoolPrint, FlowAlert


def _utc(h, m, s=0, day=18):
    return datetime(2026, 9, day, h, m, s, tzinfo=timezone.utc)


def _block(ticker, price, size, dt):
    return {"ticker": ticker, "price": price, "size": size, "dt": dt}


def _uw(ticker, price, size, dt, tid, canceled=False):
    return DarkPoolPrint(ticker=ticker, executed_at=dt.isoformat(), price=price, size=size, premium=0.0,
                         volume=1, market_center="L", canceled=canceled, nbbo_bid=None, nbbo_ask=None,
                         tracking_id=tid)


# ---- ARGUS log loading ----

def test_loader_skips_torn_and_zeroed_lines_and_counts_them(tmp_path):
    f = tmp_path / "blocks.jsonl"
    good = {"ts": "2026-09-18T14:00:00+00:00", "ticker": "SPY", "price": 750.0, "size": 300}
    f.write_text(json.dumps(good) + "\n" + "\x00" * 50 + "\n\n" + '{"ts": "torn', encoding="utf-8")

    rows, bad = argus_logs.load_dark_pool_blocks(str(f))

    assert len(rows) == 1 and bad == 2
    assert rows[0]["dt"].tzinfo is not None


def test_regular_hours_counts_flag_a_dead_detector_day():
    # 14:00 UTC = 10:00 ET (inside RTH); 22:00 UTC = 18:00 ET (outside)
    blocks = [_block("SPY", 1, 1, _utc(14, 0)), _block("SPY", 1, 1, _utc(22, 0)),
              _block("SPY", 1, 1, _utc(14, 5, day=17))]
    assert argus_logs.regular_hours_counts_by_day(blocks) == {"2026-09-18": 1, "2026-09-17": 1}


# ---- dark pool matching ----

def test_match_is_one_to_one_within_time_and_price_tolerance():
    a1 = _block("SPY", 750.00, 300, _utc(14, 0, 2))
    a2 = _block("SPY", 750.00, 300, _utc(14, 0, 3))    # same key, but only one UW print to consume
    uw = [_uw("SPY", 750.01, 300, _utc(14, 0, 0), 1)]

    r = dark_pool_match.match_blocks([a1, a2], uw)

    assert r["n_matched"] == 1 and len(r["argus_only"]) == 1
    assert r["median_lag_s"] == 2.0


def test_match_rejects_wrong_size_far_time_far_price_canceled_and_sub_floor():
    a = _block("SPY", 750.00, 300, _utc(14, 0, 0))
    uw = [
        _uw("SPY", 750.00, 301, _utc(14, 0, 0), 1),                  # size differs
        _uw("SPY", 750.00, 300, _utc(14, 5, 0), 2),                  # 5 min away
        _uw("SPY", 751.00, 300, _utc(14, 0, 0), 3),                  # price differs
        _uw("SPY", 750.00, 300, _utc(14, 0, 0), 4, canceled=True),   # canceled
    ]
    r = dark_pool_match.match_blocks([a], uw)
    assert r["n_matched"] == 0 and r["argus_match_rate"] == 0.0

    tiny = _uw("SPY", 1.00, 10, _utc(14, 0, 0), 5)                   # $10 notional, under ARGUS's floor
    assert dark_pool_match.match_blocks([], [tiny])["n_uw"] == 0


def test_uw_only_prints_are_reported_as_uw_coverage_gap():
    uw = [_uw("NVDA", 200.0, 5000, _utc(14, 0), 1)]
    r = dark_pool_match.match_blocks([], uw)
    assert r["n_uw"] == 1 and len(r["uw_only"]) == 1 and r["uw_match_rate"] == 0.0


# ---- GEX agreement ----

def _cache(gexes):
    return {f"2026-03-{i + 2:02d}": {"gex": g, "prior_day": f"2026-03-{i + 1:02d}"} for i, g in enumerate(gexes)}


def test_gex_agreement_detects_signed_convention_and_flags_wrong_one():
    argus = [-5e9, 3e9, -2e9, 4e9, -1e9, 6e9]
    cache = _cache(argus)
    # UW returns puts as NEGATIVE numbers, matching ARGUS's sign each day
    history = [DailyGreekExposure(f"2026-03-{i + 1:02d}", 10.0, -10.0 + (1 if g > 0 else -1) * 5)
               for i, g in enumerate(argus)]

    r = gex_agreement.compare_gex(cache, history)

    assert r["signed"]["n"] == 6 and r["signed"]["sign_agreement"] == 1.0
    assert r["signed"]["uw_sign_suspect"] is False


def test_gex_agreement_flags_always_positive_uw_series_as_suspect_convention():
    cache = _cache([-5e9, -3e9, -2e9, -4e9, -1e9, -6e9])
    history = [DailyGreekExposure(f"2026-03-{i + 1:02d}", 100.0, 20.0) for i in range(6)]  # puts as +magnitude

    r = gex_agreement.compare_gex(cache, history)

    assert r["signed"]["uw_sign_suspect"] is True
    assert r["signed"]["sign_agreement"] == 0.0
    assert r["magnitude"]["uw_positive_share"] == 1.0  # call - |put| is also positive here


def test_gex_pairs_on_prior_day_not_the_cache_key():
    cache = {"2026-03-10": {"gex": -1e9, "prior_day": "2026-03-09"}}
    only_key_day = [DailyGreekExposure("2026-03-10", 1.0, 1.0)]
    assert gex_agreement.compare_gex(cache, only_key_day)["signed"]["n"] == 0
    assert gex_agreement.compare_gex(cache, [DailyGreekExposure("2026-03-09", 1.0, -3.0)])["signed"]["n"] == 1


# ---- flow agreement ----

def _alert(ticker, kind, ask, bid, created_at="2026-09-18T15:00:00Z"):
    return FlowAlert(ticker=ticker, created_at=created_at, type=kind, strike=100.0, expiry="2026-09-19",
                     price=1.0, underlying_price=100.0, total_premium=ask + bid, total_ask_side_prem=ask,
                     total_bid_side_prem=bid, total_size=1, volume=1, open_interest=1, volume_oi_ratio=None,
                     has_sweep=False, has_floor=False, has_multileg=False, alert_rule="x")


def test_flow_compare_uses_regular_hours_only_and_sign_agreement():
    snaps = [
        {"dt": _utc(14, 0), "ticker": "SPY", "net_aggressive_dollar_delta": 1000.0},
        {"dt": _utc(14, 5), "ticker": "SPY", "net_aggressive_dollar_delta": 500.0},
        {"dt": _utc(22, 0), "ticker": "SPY", "net_aggressive_dollar_delta": -9e9},   # after hours: ignored
        {"dt": _utc(14, 0), "ticker": "NVDA", "net_aggressive_dollar_delta": -800.0},
    ]
    argus = flow_agreement.argus_daily_flow(snaps)
    assert argus == {("2026-09-18", "SPY"): 1500.0, ("2026-09-18", "NVDA"): -800.0}

    uw = flow_agreement.uw_daily_flow({
        ("2026-09-18", "SPY"): [_alert("SPY", "call", 900_000, 10_000)],     # bullish
        ("2026-09-18", "NVDA"): [_alert("NVDA", "call", 900_000, 10_000)],   # bullish -> disagrees with ARGUS
    })
    r = flow_agreement.compare_flow(argus, uw)

    assert r["n"] == 2 and r["sign_agreement"] == 0.5
    assert r["disagreements"] == [("2026-09-18", "NVDA")]


# ---- pagination ----

class PagingClient:
    """Serves dark-pool prints newest-first, honouring limit and older_than."""

    def __init__(self, prints):
        self.prints = sorted(prints, key=lambda p: p["executed_at"], reverse=True)
        self.calls = 0

    def get(self, path, params=None):
        self.calls += 1
        rows = self.prints
        if params.get("older_than"):
            rows = [p for p in rows if p["executed_at"] < params["older_than"]]
        return {"data": rows[: params["limit"]]}


def _raw(i, hour=14, minute=0):
    return {"ticker": "SPY", "executed_at": f"2026-09-18T{hour:02d}:{minute:02d}:{i % 60:02d}.{i:06d}Z",
            "price": "750.00", "size": 300, "premium": "0", "volume": 1, "market_center": "L",
            "canceled": False, "tracking_id": i}


def test_dark_pool_pagination_walks_cursor_and_stops_on_short_page():
    raws = [_raw(i, minute=i // 60) for i in range(25)]
    client = PagingClient(raws)

    out = uw_fetch.fetch_dark_pool_day(client, "SPY", "2026-09-18", page_limit=10)

    assert len(out) == 25 and len({p.tracking_id for p in out}) == 25
    assert client.calls == 3   # 10 + 10 + 5


def test_dark_pool_pagination_respects_page_cap():
    client = PagingClient([_raw(i, minute=i // 60) for i in range(100)])
    out = uw_fetch.fetch_dark_pool_day(client, "SPY", "2026-09-18", page_limit=10, max_pages=2)
    assert len(out) == 20 and client.calls == 2


def _raw_on(date, i, hour=14, minute=0, tid=None):
    return {"ticker": "SPY", "executed_at": f"{date}T{hour:02d}:{minute:02d}:{i % 60:02d}.{i:06d}Z",
            "price": "750.00", "size": 300, "premium": "225000", "volume": 1, "market_center": "L",
            "canceled": False, "tracking_id": i if tid is None else tid}


def test_dark_pool_fetch_stops_at_the_requested_day_instead_of_walking_into_prior_days():
    day = [_raw_on("2026-09-18", i, minute=i // 60) for i in range(15)]
    prior = [_raw_on("2026-09-17", 100 + i, minute=i // 60) for i in range(15)]
    client = PagingClient(day + prior)

    out = uw_fetch.fetch_dark_pool_day(client, "SPY", "2026-09-18", page_limit=10)

    assert {p.executed_at[:10] for p in out} == {"2026-09-18"} and len(out) == 15
    assert client.calls == 2                       # 2nd page reaches 9/17 -> stop; no 3rd page


def test_dark_pool_fetch_keeps_distinct_prints_that_share_a_tracking_id():
    a = _raw_on("2026-09-18", 1, tid=7)
    b = _raw_on("2026-09-18", 2, tid=7)            # same tracking_id, different print
    out = uw_fetch.fetch_dark_pool_day(PagingClient([a, b]), "SPY", "2026-09-18", page_limit=10)
    assert len(out) == 2


def test_alive_minutes_marks_only_minutes_where_the_detector_logged_something():
    blocks = [_block("SPY", 1, 1, _utc(14, 0, 5)), _block("QQQ", 1, 1, _utc(14, 0, 40)), _block("SPY", 1, 1, _utc(14, 3, 1))]
    assert argus_logs.alive_minutes(blocks) == {"2026-09-18 10:00", "2026-09-18 10:03"}   # 10:01, 10:02 = detector down
