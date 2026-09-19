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
