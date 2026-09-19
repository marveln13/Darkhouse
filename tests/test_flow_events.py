import pytest

from research.flow import score
from research.flow.events import EodStats, aggregate_events
from src.models import FlowAlert


def _alert(created_at, premium, ask, bid, vol_oi, *, chain="GOOGL261002C00355000", ticker="GOOGL",
           kind="call", strike=355.0, expiry="2026-10-02", price=2.85, und=331.3, multileg=False, oi=900):
    return FlowAlert(ticker=ticker, created_at=created_at, type=kind, strike=strike, expiry=expiry, price=price,
                     underlying_price=und, total_premium=premium, total_ask_side_prem=ask, total_bid_side_prem=bid,
                     total_size=1000, volume=5000, open_interest=oi, volume_oi_ratio=vol_oi, has_sweep=False,
                     has_floor=False, has_multileg=multileg, alert_rule="RepeatedHits", option_chain=chain)


def _row(**kw):
    """Shaped like a /historic row; defaults model the leader's GOOGL 355C day (2026-09-10)."""
    base = dict(volume=19_078, open_interest=900, ask_volume=11_830, bid_volume=5_100, floor_volume=7_030,
                multi_leg_volume=700, total_premium="5265507.00", open_price="2.45", high_price="3.05",
                low_price="2.27", last_price="2.86", avg_price="2.76")
    return {**base, **kw}


def _event(row=None, **alert_kw):
    ev = aggregate_events([_alert("2026-09-10T14:27:26Z", 261_380, 261_380, 0, 1.2, **alert_kw)])[0]
    ev.eod = EodStats.from_row(row or _row())
    return ev


def test_events_group_by_contract_and_et_day_and_sum_alert_premium():
    other_day = _alert("2026-09-11T14:00:00Z", 100_000, 100_000, 0, 1.0)
    other_contract = _alert("2026-09-10T14:00:00Z", 100_000, 100_000, 0, 1.0, chain="GOOGL260925P00270000")
    three = [_alert("2026-09-10T14:27:26Z", 261_380, 261_380, 0, 1.2), _alert("2026-09-10T14:32:38Z", 268_533, 268_533, 0, 2.3),
             _alert("2026-09-10T14:36:31Z", 225_498, 225_498, 0, 4.4)]

    events = aggregate_events(three + [other_day, other_contract])

    assert len(events) == 3
    ev = next(e for e in events if e.chain == "GOOGL261002C00355000" and e.date == "2026-09-10")
    assert ev.n_alerts == 3 and abs(ev.cum_premium - 755_411) < 1 and ev.dte == 22
    assert ev.first_price == 2.85 and abs(ev.otm_pct - 7.15) < 0.01


def test_alerts_without_a_contract_symbol_are_skipped():
    assert aggregate_events([_alert("2026-09-10T14:00:00Z", 1, 1, 0, 1.0, chain=None)]) == []


def test_eod_stats_reproduce_the_leaders_screenshot_quality():
    eod = EodStats.from_row(_row())
    assert round(eod.vol_oi) == 21 and round(eod.ask_share, 2) == 0.70
    assert round(eod.floor_share, 2) == 0.37 and eod.multileg_share < 0.04


def test_the_leaders_example_scores_the_maximum_on_end_of_day_data():
    ev = _event()

    assert score.components(ev) == {"size": 2, "opening": 2, "aggression": 1, "floor": 1,
                                    "single_leg": 1, "horizon": 1, "otm": 1}
    assert score.score(ev) == 9 and score.bucket(ev) == "high"
    assert score.direction(ev) == "bullish"


def test_scoring_without_end_of_day_stats_fails_loudly_instead_of_silently_using_alerts():
    ev = aggregate_events([_alert("2026-09-10T14:00:00Z", 1, 1, 0, 1.0)])[0]
    with pytest.raises(ValueError):
        score.score(ev)


def test_components_hit_their_thresholds_exactly():
    at = _event(_row(total_premium="2000000", volume=13_500, ask_volume=650, bid_volume=350, floor_volume=3_375,
                     multi_leg_volume=2_700))
    parts = score.components(at)
    assert parts["size"] == 2 and parts["opening"] == 2          # 13,500/900 = 15x exactly
    assert parts["aggression"] == 1 and parts["floor"] == 1      # 65% ask, 25% floor: exactly on the lines
    assert parts["single_leg"] == 0                              # 20% multi-leg is NOT under the 20% cap

    below = _event(_row(total_premium="499999", volume=4_499, ask_volume=500, bid_volume=500, floor_volume=0))
    parts = score.components(below)
    assert parts["size"] == 0 and parts["opening"] == 0 and parts["aggression"] == 0 and parts["floor"] == 0


def test_horizon_and_moneyness_gates():
    ev = _event(expiry="2026-09-12", strike=331.0)
    parts = score.components(ev)
    assert parts["horizon"] == 0 and parts["otm"] == 0            # 2 DTE and ITM


def test_direction_covers_all_call_put_side_combinations():
    def d(kind, ask, bid):
        return score.direction(_event(_row(ask_volume=ask, bid_volume=bid), kind=kind))

    assert d("call", 90, 10) == "bullish"     # bought calls
    assert d("call", 10, 90) == "bearish"     # sold calls
    assert d("put", 90, 10) == "bearish"      # bought puts
    assert d("put", 10, 90) == "bullish"      # sold puts
    assert d("call", 50, 50) is None          # no side dominance -> no signal


def test_put_moneyness_is_measured_the_right_way_round():
    ev = aggregate_events([_alert("2026-09-10T14:00:00Z", 1, 1, 0, 1.0, kind="put", strike=300.0, und=330.0)])[0]
    assert abs(ev.otm_pct - 9.09) < 0.01      # a 300 put with the stock at 330 is 9% OTM, not -10%
