"""
PRE-REGISTERED flow conviction score (committed before any outcome data across
events was examined; the git commit timestamp is the registration).

Inputs are END-OF-DAY contract stats (/api/option-contract/{id}/historic), not
flow-alert aggregates: on the leader's own GOOGL example the alerts showed $755k
and 4.4x volume/OI while the contract's real day was $5.3M and 21x, so alerts
understate exactly the flow he trades. Alerts are used only to DISCOVER
contracts. Scores use day-D data and are traded no earlier than D+1, so there is
no lookahead.

Components mirror the criteria visible in his GOOGL 10/02 $355C call
(2026-09-10): a big contract, volume far above open interest (new positions),
aggressive ask-side buying, floor prints, single-leg (directional, not a
spread), a multi-week horizon, and a moderately-OTM strike. His conviction is
graded (position size, "keeping it lite"), so the score is graded, not yes/no.

Thresholds come from that one example plus common unusual-options conventions.
They are NOT to be tuned on outcomes; robustness is checked only by moving one
threshold at a time and reporting every row.

Max score 9.  Pre-registered bins:  low 0-3 | mid 4-6 | high 7-9.
Direction:  bullish = call flow that is ask-dominant OR put flow that is
bid-dominant;  bearish = put ask-dominant OR call bid-dominant.  Flow that is
neither side-dominant has no direction and is not a signal.
"""
SIZE_MID, SIZE_HIGH = 500_000, 2_000_000          # day total premium, USD
VOL_OI_MID, VOL_OI_HIGH = 5.0, 15.0               # day volume / start-of-day open interest
DOMINANCE = 0.65                                   # ask (or bid) share of side-attributed volume
FLOOR_SHARE = 0.25                                 # floor volume / total volume
MULTILEG_MAX = 0.20                                # multi-leg volume share treated as still directional
DTE_MIN, DTE_MAX = 10, 45
OTM_MIN, OTM_MAX = 2.0, 12.0                       # percent out of the money
HIGH_CUTOFF, MID_CUTOFF = 7, 4


def _require_eod(event):
    if event.eod is None:
        raise ValueError("score needs end-of-day contract stats; attach them from /historic first")
    return event.eod


def components(event):
    eod = _require_eod(event)
    share = eod.ask_share
    dominant = share is not None and max(share, 1 - share) >= DOMINANCE
    vol_oi = eod.vol_oi or 0.0
    return {
        "size": 2 if eod.total_premium >= SIZE_HIGH else 1 if eod.total_premium >= SIZE_MID else 0,
        "opening": 2 if vol_oi >= VOL_OI_HIGH else 1 if vol_oi >= VOL_OI_MID else 0,
        "aggression": 1 if dominant else 0,
        "floor": 1 if eod.floor_share >= FLOOR_SHARE else 0,
        "single_leg": 1 if eod.multileg_share < MULTILEG_MAX else 0,
        "horizon": 1 if DTE_MIN <= event.dte <= DTE_MAX else 0,
        "otm": 1 if OTM_MIN <= event.otm_pct <= OTM_MAX else 0,
    }


def score(event):
    return sum(components(event).values())


def bucket(event):
    s = score(event)
    return "high" if s >= HIGH_CUTOFF else "mid" if s >= MID_CUTOFF else "low"


def direction(event):
    share = _require_eod(event).ask_share
    if share is None or max(share, 1 - share) < DOMINANCE:
        return None
    ask_side = share >= DOMINANCE
    if event.type == "call":
        return "bullish" if ask_side else "bearish"
    return "bearish" if ask_side else "bullish"
