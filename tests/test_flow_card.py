import pytest

from research.flow import card, score
from research.flow.events import event_from_contract_day, parse_osi

ROW = dict(volume=19_078, open_interest=900, ask_volume=11_830, bid_volume=5_100, floor_volume=7_030,
           multi_leg_volume=700, total_premium="5265507.00", open_price="2.45", high_price="3.05",
           low_price="2.27", last_price="2.86", avg_price="2.76")


def test_parse_osi_reads_root_expiry_type_and_strike():
    root, expiry, kind, strike = parse_osi("GOOGL261002C00355000")
    assert (root, expiry.isoformat(), kind, strike) == ("GOOGL", "2026-10-02", "call", 355.0)
    assert parse_osi("SPY260919P00445500")[2:] == ("put", 445.5)
    with pytest.raises(ValueError):
        parse_osi("not-a-symbol")


def test_a_contract_day_event_scores_the_leaders_example_at_the_maximum():
    ev = event_from_contract_day("GOOGL261002C00355000", "2026-09-10", ROW, underlying_price=329.89)
    assert score.score(ev) == 9 and score.direction(ev) == "bullish" and ev.dte == 22


def test_the_card_shows_the_score_every_component_and_the_size_reference():
    ev = event_from_contract_day("GOOGL261002C00355000", "2026-09-10", ROW, underlying_price=329.89)

    page = card.render_card(ev, equity=100_000)

    assert "9<small> / 9</small>" in page and "bullish" in page and "high conviction" in page
    for name in ("size", "opening", "aggression", "floor", "single leg", "horizon", "otm"):
        assert name in page
    assert "large account ($100,000)" in page
    assert "start 1: 1 &rarr; 3 &rarr; 5 &rarr; 6" in page          # $2,000 / $286 = 6 contracts at full size
    assert "start 2: 2 &rarr; 4 &rarr; 6" in page
    assert "does not set size" in page and "Not investment advice" in page


def test_the_card_handles_a_small_account_that_cannot_afford_the_contract():
    ev = event_from_contract_day("GOOGL261002C00355000", "2026-09-10", ROW, underlying_price=329.89)
    page = card.render_card(ev, equity=4_000)
    assert "small account" in page and "not affordable" in page


def test_untrusted_text_is_escaped():
    ev = event_from_contract_day("GOOGL261002C00355000", "2026-09-10", ROW, underlying_price=329.89)
    ev.ticker = "<script>x</script>"
    assert "<script>x</script>" not in card.render_card(ev, equity=100_000)
