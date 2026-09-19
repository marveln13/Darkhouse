import pytest

from research.flow import sizing


def test_account_tiers_and_their_exact_boundaries():
    assert sizing.tier(4_999.99) == "small" and sizing.tier(5_000) == "medium"
    assert sizing.tier(49_999.99) == "medium" and sizing.tier(50_000) == "large"
    assert sizing.tier(100_000) == "large"                      # the paper account


def test_size_scale_is_a_quarter_a_half_and_all_of_two_percent():
    assert sizing.size_pct("lite_starter") == pytest.approx(0.005)
    assert sizing.size_pct("half") == pytest.approx(0.01)
    assert sizing.size_pct("full") == pytest.approx(0.02)


def test_lite_starter_on_the_paper_account_reaches_the_leaders_two_contract_minimum():
    assert sizing.contracts("lite_starter", 100_000, 2.50) == 2   # $500 budget / $250 per contract
    assert sizing.contracts("lite_starter", 100_000, 2.85) == 1   # $570 per contract does not fit in $500


def test_half_and_full_on_the_paper_account_at_the_leaders_entry_price():
    assert sizing.contracts("half", 100_000, 2.85) == 3           # $1,000 / $285
    assert sizing.contracts("full", 100_000, 2.85) == 7           # $2,000 / $285


def test_a_small_account_gets_zero_rather_than_a_forced_oversized_contract():
    assert sizing.contracts("full", 5_000 - 1, 2.85) == 0         # 1 contract = 5.7% of the account > 2% full
    assert sizing.contracts("full", 4_000, 0.80) == 1             # $80 fits inside the $80 full-size budget


def test_the_budget_is_never_exceeded_by_rounding():
    for equity in (3_000, 12_000, 48_000, 100_000, 250_000):
        for premium in (0.35, 1.20, 2.85, 7.00):
            for term in sizing.SIZE_FRACTIONS:
                n = sizing.contracts(term, equity, premium)
                assert n * premium * 100 <= sizing.size_pct(term) * equity + 1e-9


def test_bad_inputs_fail_loudly():
    with pytest.raises(KeyError):
        sizing.contracts("yolo", 100_000, 2.0)
    with pytest.raises(ValueError):
        sizing.contracts("full", 100_000, 0)


def test_labels_use_the_users_vocabulary_with_full_and_above_being_heavy():
    assert sizing.label(0.0020) == "lotto" and sizing.label(0.0025) == "lotto"
    assert sizing.label(0.0040) == "lite_starter" and sizing.label(0.0050) == "lite_starter"
    assert sizing.label(0.0080) == "half" and sizing.label(0.0100) == "half"
    assert sizing.label(0.0150) == "scaling"
    assert sizing.label(0.0200) == "heavy"                     # full size itself is heavy
    assert sizing.label(0.0350) == "heavy"


def test_lotto_is_a_quarter_percent_of_equity():
    assert sizing.lotto_contracts(100_000, 1.00) == 2          # $250 budget / $100 per contract
    assert sizing.lotto_contracts(100_000, 2.85) == 0          # too pricey to be a lotto in this account


def test_scale_in_starts_with_one_or_two_and_adds_two_at_a_time_to_full():
    # $100k at $2.85 -> full = 7 contracts
    assert sizing.scale_in_plan(100_000, 2.85, first=1) == [1, 3, 5, 7]
    assert sizing.scale_in_plan(100_000, 2.85, first=2) == [2, 4, 6, 7]     # last add trimmed 2 -> 1: no overshoot


def test_a_fully_scaled_in_position_lands_on_full_size_which_is_heavy_and_never_beyond():
    for premium in (0.90, 1.40, 2.85, 4.10):
        for first in (1, 2):
            plan = sizing.scale_in_plan(100_000, premium, first=first)
            if plan:
                assert plan[-1] == sizing.contracts("full", 100_000, premium)
                assert plan[-1] * premium * 100 <= sizing.FULL_PCT * 100_000 + 1e-9
                assert sizing.label_position(plan[-1], 100_000, premium) == "heavy"
                assert all(sizing.label_position(n, 100_000, premium) != "heavy" for n in plan[:-1])


def test_label_position_judges_full_by_contract_count_not_an_exact_two_percent():
    assert 7 * 2.85 * 100 / 100_000 < sizing.FULL_PCT            # 1.995%: below 2.00% exactly...
    assert sizing.label_position(7, 100_000, 2.85) == "heavy"    # ...but it IS full size
    assert sizing.label_position(6, 100_000, 2.85) == "scaling"
    assert sizing.label_position(8, 100_000, 2.85) == "heavy"    # above full
    assert sizing.label_position(1, 100_000, 2.85) == "lite_starter"   # $285 = 0.285%
    assert sizing.label_position(1, 100_000, 0.80) == "lotto"          # $80 = 0.08%
    assert sizing.label_position(1, 4_000, 2.85) == "heavy"            # 7% of a small account


def test_scale_in_is_empty_when_the_first_entry_alone_exceeds_full_size():
    assert sizing.scale_in_plan(4_000, 2.85) == []
    with pytest.raises(ValueError):
        sizing.scale_in_plan(100_000, 2.85, first=3)
