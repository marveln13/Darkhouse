"""
PRE-REGISTERED evaluation protocol for the flow conviction score
(research/flow/score.py). Committed before any cross-event outcome was
examined. Disclosure: the price path of the leader's single GOOGL 10/02 $355C
example was seen while building the score; no other outcome was.

QUESTION.  Does higher flow conviction predict better forward results? (a
dose-response test -- if his graded "judgment" tracks something real, results
should rise across the low / mid / high buckets.)

UNIVERSE.  Contract-days discovered from UW flow alerts (calls and puts) over
the API's lookback, then enriched with that contract's end-of-day stats.
Directional events only (score.direction is not None).

TIMING.  Features use day D only. No trade is assumed before D+1.

PRIMARY OUTCOME 1 -- underlying.  Direction-signed return of the underlying from
the close of D to the close of D+5, minus SPY's return over the same window
(bullish = +, bearish = -). Answers "did the flow point the right way" with no
option-pricing noise.

PRIMARY OUTCOME 2 -- the contract itself (ask-dominant events only, i.e. the
trades a follower could actually copy by BUYING the same contract): return from
D+1 open_price to D+6 avg_price. Reported net and gross of a half-spread haircut
taken from D's closing NBBO width.

ANALYSIS.  Mean outcome per bucket; monotonic trend across score 0-9 (Spearman);
high minus low with standard errors CLUSTERED BY DAY (flow on one day is
correlated across tickers); a first-half / second-half split by date; a
permutation test that shuffles scores within calendar month; and a null
result is reported as a null.

NOT ALLOWED.  Changing any threshold in score.py, the horizons below, or the
event definition after seeing outcomes. Sensitivity = move ONE thing at a time
and print every row.
"""
UNDERLYING_HORIZON_DAYS = 5
CONTRACT_ENTRY = "next_day_open"        # D+1 open_price
CONTRACT_EXIT_DAYS = 5                  # D+6 avg_price (five trading days after entry)
BENCHMARK = "SPY"


# ---- Addendum (still BEFORE any outcome was fetched): concrete pull parameters ----
# Feasibility-driven and identical for every bucket, chosen after seeing only alert
# COUNTS, never outcomes. A contract's /historic call returns its whole daily history,
# so enrichment costs one call per unique contract, not per contract-day.
#
# AMENDMENT (still before any outcome): the first pull used the API's min_dte/max_dte.
# Verified live that the server evaluates DTE relative to TODAY, not the alert's date:
# on 2025-10-15 it removed 99% of alerts (4,968 -> 39), keeping only contracts that had
# not yet expired (LEAPS), so older months would have been a different population.
# The 7-90 day window is now applied client-side from each alert's own date.
DISCOVERY_FILTERS = {"min_premium": 50_000, "issue_types[]": ["Common Stock"]}
DISCOVERY_DTE = (7, 90)

# ---- Addendum 2 (before ANY outcome was computed; enrichment had only fetched raw data) ----
# Statistical details the protocol left open. Fixed now so none can be chosen after the fact.
MIN_ENTRY_PRICE = 0.10          # contract entry (D+1 open) below $0.10: % returns are tick noise, excluded
WINSOR = (0.01, 0.99)           # every outcome is winsorized at these quantiles before averaging
# Headline statistic per outcome: winsorized mean of (high bucket) minus (low bucket); medians and hit
# rates are reported alongside. Missing D+1 / D+6 contract rows exclude an event from outcome 2 (a
# follower could not have been filled); exclusion counts are reported BY BUCKET so differential
# attrition is visible. The half-spread haircut is (ask-bid)/(ask+bid) from D's last NBBO, paid on entry
# and exit; if D's NBBO is missing or crossed, only the gross figure is reported for that event.
# Inference: 2,000 day-level bootstrap resamples and 2,000 within-calendar-month score permutations
# (both seeded), two-sided. Primary universe = events passing ENRICH_MIN_ALERT_PREMIUM; the seeded
# leakage sample is used only to estimate what the cutoff excluded.
# Addendum 3 (the first analysis run crashed BEFORE computing any statistic): real /historic rows can carry
# null price fields (days with no usable trade). Such a row is treated exactly like a missing row -- excluded
# from outcome 2 with status "no_price", counted by bucket in the attrition report.
BOOTSTRAP_RESAMPLES = PERMUTATIONS = 2_000
STAT_SEED = 20260918
DISCOVERY_START, DISCOVERY_END = "2025-09-19", "2026-09-17"
ENRICH_MIN_ALERT_PREMIUM = 250_000     # a contract-day's summed alert premium; alerts understate the real day
LEAKAGE_SAMPLE_FRAC, LEAKAGE_SEED = 0.05, 20260918   # seeded random slice of the excluded events, enriched
                                                     # anyway to measure how many would have scored high
