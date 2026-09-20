# Pre-registration: do prior-day UW levels filter ARGUS's M30i PUTS signals?

Written 2026-09-20, committed BEFORE any UW data is fetched for this study and before any outcome is joined to any level.
Anything not fixed here is not allowed to change after results; changes go in the Addenda log at the bottom, dated, before the
results they affect are seen.

## Why this study exists
The goal is a profitable auto-trader. Two earlier UW studies were null, but both used generic levels/flow events, not ARGUS's own
signal populations (README, Findings 1-2 and the flow-conviction study). If UW data adds edge for ARGUS, the likeliest place is as a
FILTER on a setup that already has an edge. This is the one UW test directly tied to that goal. If it is null, UW work stops
(hackathon submission aside).

## Population (fixed)
- **Primary: M30i PUTS.** Loud M30 liquidity-sweep signals (rvol_20 >= RVOL_20_LOUD_THRESHOLD, currently 1.01), deduped earliest,
  mirrored to puts, built by the SAME functions the ARGUS backtests use (`find_signals_with_all_factors`, `dedup_earliest`,
  `atr_series`, `load_cached_m30`). Stop = mirrored stop, target = 3R below entry (TARGET_R_MULTIPLE), HOLD_BARS = 13, outcome
  simulated by `trade_simulator.simulate_trade` exactly as in the existing put backtests. Outcome = R (stock-level).
- **Window:** signals dated within the last 12 months of cached data (matches the flow study's window; UW history is dense there).
- **Replication only: ORB UP.** Its signal population and outcome must be pinned (module + function + parameters written into
  Addendum 0) BEFORE any UW data is fetched for it. Until then it is not part of the study.

## Levels (fixed; lookahead-safe)
For a signal on session D, levels come ONLY from UW data of the prior trading session D-1 (never D). Definitions reuse
`research/levels.py`: the top-5 dark-pool price levels by volume, plus the GEX fields call_wall, put_wall, gamma_flip,
gamma_magnet from the by-strike GEX snapshot of D-1. A signal with missing D-1 dark-pool OR GEX data is excluded and counted.
A test must assert every fetch date is strictly earlier than the signal date.

## Hypotheses (two primary, fixed direction, both tested two-sided)
- **H1 obstacle:** M30i PUTS signals with >= 1 D-1 level strictly inside the path from entry down to the 3R target
  (target <= level < entry) have LOWER mean R than signals with none. (A put's path to target crossing support is an obstacle.)
- **H2 regime:** signals whose entry price is BELOW D-1 gamma_flip (negative-gamma zone) have HIGHER mean R than signals above it.
  (Theory: negative gamma amplifies moves; the earlier VIX1D result pointed the same way.)

Multiplicity: exactly these two; Holm correction at alpha = 0.05. Everything else below is exploratory and gets no verdict.

## Statistics (fixed)
- Effect = mean R(group A) - mean R(group B), with a DAY-CLUSTERED bootstrap (2,000 resamples of signal days, seed 20260921) for
  the 95% CI and p. Naive t is reported but never used for the verdict (sweeps cluster by day; see the flip study).
- Halves: split signals by date at the median; report the effect in each half.
- **Placebo (mandatory):** repeat H1 with every level shifted by a seeded random amount U(0.5%, 1.5%) in a random direction.
  The placebo effect must be smaller than half of the real effect.
- Base rates: report the share of signals in each group and the unconditional mean R, so the effect is interpretable.

## Verdict rules (fixed now)
A hypothesis is **SUPPORTED** only if ALL hold: Holm-adjusted p < 0.05; the same sign in both halves; placebo passes;
|effect| >= 0.05R. Otherwise it is **NOT SUPPORTED**. An underpowered result is reported as such, not as a null.
- Power statement: with n ~ 2,000 and per-trade SD ~ 1.2R, only an effect of roughly 0.15R or more is detectable after day
  clustering. A null therefore means "no large effect", not "zero".
- **Minimum sample:** if fewer than 1,500 signals have complete data, the verdict is "underpowered -- no verdict".

## What happens next (fixed now)
- Either hypothesis SUPPORTED -> a second stage on data not used here (later dates, or the forward log) with the same rules,
  BEFORE any ARGUS wiring. M30i PUTS stays frozen until 25 reps regardless.
- Neither supported -> stop UW-as-a-filter work; do not renew UW past the credit; record in memory.
- No re-running with new definitions to "rescue" a result.

## Data plan and quota (fixed)
- Unique (ticker, D-1) pairs are put in a seeded random order (seed 20260921) and fetched until the budget is spent:
  at most 39,850 requests per UW quota day (`x-uw-daily-req-count`), at most 3 quota days (resets 8 PM ET). Because the order is
  random, the completed set is a random sample; analysis uses whatever completed. The fetch script must not read outcomes.
- Analysis runs ONCE, after the fetch stops. No interim looks at outcomes.
- Raw UW data stays in the gitignored `.cache/` (UW terms: personal use, no redistribution). Only aggregate tables are committed.

## Known limits (stated up front)
Stock-level R only: no option premiums, no spreads, no premium stops (the live setup exits mostly on premium stops -- see the
COHR/SWKS/HPE spread findings). A stock-level edge is necessary, not sufficient. D-1 levels are a day stale by construction.
One year of data, one setup as primary.

## Implementation checklist (before fetching)
1. Export the signal table (ticker, date, entry, stop, target, R) from the ARGUS repo to `.cache/` (not committed).
2. Fetch script using the caching, quota-aware client; no access to outcomes.
3. Analysis script implementing exactly the above; tests for the D-1 rule, the in-path rule, Holm, the placebo shift, and the
   verdict logic (mutation-check the verdict rule).
4. Pin the ORB UP population in Addendum 0.

## Addenda log
(none yet)
