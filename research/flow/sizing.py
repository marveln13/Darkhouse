"""
Position-size vocabulary as a share of account equity in option premium (the
worst-case loss on a long option). Decided with the user 2026-09-19.

Why percentages: a group trader's "lite starter" (2-5 contracts) only means
"small" relative to an account. The same 2-5 contracts of a $2.85 option are
0.6-1.4% of $100k but 11-29% of $5k. Full size = 2% of equity, matching ARGUS's
existing per-trade cap (MAX_RISK_PCT_OF_EQUITY), so even a total loss on a
full-size position stays inside the account's own risk limits.

Calibration note: at a $100k account, "lite starter" = 0.5% = $500 = 2 contracts
of a $2.50 option -- the low end of the leader's stated 2-5 contract range. His
upper end (5 contracts ~ 1.25%) sits nearer "half" on this scale. That is
expected: his account size is unknown, so his contract count is only a rough
anchor for the percentage scale, not a definition of it.
"""
SMALL_BELOW = 5_000          # Small  : equity < $5k
LARGE_FROM = 50_000          # Medium : $5k <= equity < $50k ; Large: equity >= $50k
FULL_PCT = 0.02
SIZE_FRACTIONS = {"lite_starter": 0.25, "half": 0.5, "full": 1.0}
CONTRACT_MULTIPLIER = 100


def tier(equity):
    if equity < SMALL_BELOW:
        return "small"
    return "medium" if equity < LARGE_FROM else "large"


def size_pct(term):
    return FULL_PCT * SIZE_FRACTIONS[term]


def contracts(term, equity, premium_per_share):
    """Whole contracts that fit inside the size budget. Never rounds UP past the budget: 0 means the
    contract is too expensive for this account at this size (a small account must pick a cheaper
    contract rather than exceed its risk limit)."""
    cost = premium_per_share * CONTRACT_MULTIPLIER
    if cost <= 0:
        raise ValueError("premium must be positive")
    return int(size_pct(term) * equity // cost)
