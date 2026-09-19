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
# "Lottery ticket": small enough that a 100% loss doesn't matter. The user gave that as a tolerance,
# not a number; 0.25% of equity (half a lite starter). Confirmed by the user 2026-09-19: "good for now".
LOTTO_PCT = 0.0025
ADD_CONTRACTS = 2            # every add while scaling in is 2 contracts
FIRST_ENTRY_CHOICES = (1, 2)   # a scaled position starts with 1 or 2 contracts


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


def lotto_contracts(equity, premium_per_share):
    cost = premium_per_share * CONTRACT_MULTIPLIER
    return int(LOTTO_PCT * equity // cost)


def label(pct_of_equity):
    """Name a position by its premium as a share of equity. Full size and anything above it is HEAVY
    (user's definition), so 'full' is the threshold, not a separate label."""
    if pct_of_equity >= FULL_PCT:
        return "heavy"
    if pct_of_equity <= LOTTO_PCT:
        return "lotto"
    if pct_of_equity <= size_pct("lite_starter"):
        return "lite_starter"
    if pct_of_equity <= size_pct("half"):
        return "half"
    return "scaling"             # between half and full: a position still being built toward full


def label_position(n_contracts, equity, premium_per_share):
    """Label a whole-contract position. With integer contracts a full-size position almost never equals
    2.00% exactly (7 x $285 = 1.995% of $100k), so 'at or above full' is judged by contract count as
    well as by percentage. Note the consequence: on a small account a single pricey contract is HEAVY."""
    pct = n_contracts * premium_per_share * CONTRACT_MULTIPLIER / equity
    full = contracts("full", equity, premium_per_share)
    if pct >= FULL_PCT or (full > 0 and n_contracts >= full):
        return "heavy"
    return label(pct)


def scale_in_plan(equity, premium_per_share, first=2):
    """Cumulative contract counts after each entry: start with `first` (1 or 2), add 2 at a time until
    full size is reached, then stop. The final add is trimmed so the position lands ON full size rather
    than overshooting the 2% budget; going above full (still 'heavy') would be a separate, deliberate
    decision. By the user's definition the finished position is itself heavy. Empty if `first` alone
    doesn't fit inside full size."""
    if first not in FIRST_ENTRY_CHOICES:
        raise ValueError(f"a scaled position starts with {FIRST_ENTRY_CHOICES} contracts")
    full = contracts("full", equity, premium_per_share)
    if first > full:
        return []
    plan = [first]
    while plan[-1] < full:
        plan.append(min(plan[-1] + ADD_CONTRACTS, full))
    return plan
