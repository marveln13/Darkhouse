from datetime import datetime
from types import SimpleNamespace

from compare.argus_logs import ET
from research import reaction
from research.caching_client import CachingClient
from research.levels import label_levels
from src.models import DarkPoolPriceLevel, DarkPoolPriceLevels, GexLevels


def bar(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c, "date": "2026-09-01",
            "dt": datetime(2026, 9, 1, 9, 30, tzinfo=ET)}


def flat(n, price=100.0, rng=1.0):
    return [bar(price, price + rng / 2, price - rng / 2, price) for _ in range(n)]


# ---- level labelling ----

def _levels(*pairs):
    return DarkPoolPriceLevels("SPY", "2026-09-01", [DarkPoolPriceLevel(p, v, 1000) for p, v in pairs])


def _gex(**kw):
    base = dict(ticker="SPY", date="d", source="oi", time="t", call_wall=None, put_wall=None,
                gamma_flip=None, gamma_magnet=None)
    return GexLevels(**{**base, **kw})


def test_labels_confluence_dp_only_gex_only_and_two_placebos_per_confluence():
    levels = _levels((440.0, 900), (450.0, 800), (430.0, 1))    # 430 is not heavy at top_n=2
    gex = _gex(gamma_flip=440.10, call_wall=470.0)

    out = label_levels(levels, gex, top_n=2, proximity_pct=0.5, placebo_shift_pct=1.0)
    groups = sorted((o["group"], round(o["price"], 2)) for o in out)

    assert ("confluence", 440.0) in groups
    assert ("dp_only", 450.0) in groups
    assert ("gex_only", 470.0) in groups
    assert ("placebo", 444.4) in groups and ("placebo", 435.6) in groups
    assert not any(p == 430.0 for _, p in groups)


# ---- touch detection ----

def test_touch_side_follows_where_price_came_from_and_gaps_over_a_level_do_not_touch():
    down = [bar(102, 102.5, 101.5, 102), bar(101, 101.2, 99.8, 100.5)]
    assert reaction.find_touch(down, 0, 2, 100.0) == (1, "support")           # came from above

    up = [bar(98, 98.5, 97.5, 98), bar(99, 100.3, 98.9, 99.8)]
    assert reaction.find_touch(up, 0, 2, 100.0) == (1, "resistance")          # came from below

    gap = [bar(98, 98.5, 97.5, 98), bar(103, 104, 102.5, 103)]                # jumped over 100
    assert reaction.find_touch(gap, 0, 2, 100.0) is None


# ---- outcome classification ----

def _support_touch_then(next_bars):
    bars = [bar(102, 102.5, 101.5, 102), bar(101, 101.2, 99.8, 100.4)] + next_bars
    return bars, 1, len(bars)


def test_support_holds_when_price_rallies_k_atr_before_breaking_through():
    bars, idx, end = _support_touch_then([bar(100.4, 101.2, 100.2, 101.0)])
    assert reaction.classify(bars, idx, end, 100.0, "support", atr=1.0, k=0.5, horizon=4) == "hold"


def test_support_breaks_when_price_falls_k_atr_through_first():
    bars, idx, end = _support_touch_then([bar(100.4, 100.3, 99.3, 99.4)])
    assert reaction.classify(bars, idx, end, 100.0, "support", atr=1.0, k=0.5, horizon=4) == "break"


def test_resistance_is_the_mirror_image():
    bars = [bar(98, 98.5, 97.5, 98), bar(99, 100.3, 98.9, 99.8), bar(99.8, 99.9, 99.2, 99.3)]
    assert reaction.classify(bars, 1, 3, 100.0, "resistance", atr=1.0, k=0.5, horizon=4) == "hold"


def test_timeout_ambiguous_horizon_and_session_end():
    quiet, idx, end = _support_touch_then([bar(100.2, 100.3, 100.1, 100.2)] * 3)
    assert reaction.classify(quiet, idx, end, 100.0, "support", 1.0, 0.5, 4) == "timeout"

    wild, idx, end = _support_touch_then([bar(100.4, 101.0, 99.4, 100.0)])
    assert reaction.classify(wild, idx, end, 100.0, "support", 1.0, 0.5, 4) == "ambiguous"

    late, idx, end = _support_touch_then([bar(100.2, 100.3, 100.1, 100.2), bar(100.2, 101.5, 100.1, 101.4)])
    assert reaction.classify(late, idx, end, 100.0, "support", 1.0, 0.5, horizon=1) == "timeout"  # reaction after the horizon
    assert reaction.classify(late, idx, 3, 100.0, "support", 1.0, 0.5, horizon=4) == "timeout"    # session ends before it


def test_atr_uses_only_bars_before_the_touch_no_lookahead():
    bars = flat(20, rng=1.0)
    before = reaction.atr_before(bars, 15)
    bars[16:] = [bar(100, 150, 50, 100)] * 4          # violent FUTURE bars
    assert reaction.atr_before(bars, 15) == before


def test_events_for_day_end_to_end_measures_only_the_next_session():
    history = flat(20)
    session = [bar(102, 102.4, 101.6, 102), bar(101, 101.2, 99.8, 100.4), bar(100.4, 101.3, 100.2, 101.1)]
    bars = history + session
    labelled = [{"price": 100.0, "group": "confluence"}, {"price": 300.0, "group": "dp_only"}]

    events = reaction.events_for_day("SPY", "2026-09-02", bars, (20, 23), labelled, k=0.5, horizon=4)

    assert len(events) == 1                                   # the 300 level never touched
    assert events[0]["group"] == "confluence" and events[0]["side"] == "support"
    assert events[0]["outcome"] == "hold"


# ---- statistics ----

def _ev(group, outcome, i):
    return {"ticker": "SPY", "date": f"d{i}", "group": group, "side": "support", "level": 1.0, "outcome": outcome}


def test_compare_groups_detects_a_real_difference_and_not_a_null_one():
    strong = [_ev("confluence", "hold" if i % 10 else "break", i) for i in range(200)]      # ~90% hold
    weak = [_ev("dp_only", "hold" if i % 2 else "break", i) for i in range(200)]            # 50%
    r = reaction.compare_groups(strong + weak)
    assert r["t"] > 9 and r["p"] < 1e-6   # hand-computed t ~ 9.7 for 90% vs 50%, n=200 each

    same = [_ev("confluence", "hold" if i % 2 else "break", i) for i in range(200)]
    null = reaction.compare_groups(same + weak)
    assert abs(null["t"]) < 1e-9 and null["p"] == 1.0


def test_hold_rate_ignores_timeouts_and_ambiguous():
    ev = [_ev("g", "hold", 0), _ev("g", "break", 1), _ev("g", "timeout", 2), _ev("g", "ambiguous", 3)]
    assert reaction.hold_rate(ev) == 0.5


def test_statistics_use_ticker_day_clusters_not_raw_events():
    ev = [_ev("confluence", "hold", 1)] * 50 + [_ev("confluence", "break", 2)]
    assert sorted(reaction.cluster_means(ev, "confluence")) == [0.0, 1.0]   # 51 events, 2 clusters


# ---- cache ----

def test_caching_client_only_calls_the_api_once_per_distinct_request(tmp_path):
    calls = []
    inner = SimpleNamespace(get=lambda path, params=None: calls.append((path, params)) or {"data": [1]})
    c = CachingClient(inner, str(tmp_path))
    assert c.get("/x", {"a": 1}) == c.get("/x", {"a": 1}) == {"data": [1]}
    c.get("/x", {"a": 2})
    assert len(calls) == 2
