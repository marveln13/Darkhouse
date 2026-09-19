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
