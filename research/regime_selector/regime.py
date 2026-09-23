"""The regime series: pure functions over UW's daily SPY greek-exposure rows (PREREGISTRATION.md, "Regime")."""
import bisect

from research.regime_selector import protocol


def series(rows):
    """[(date, net_gamma)] oldest first, one row per session (net = call + put; put gamma is signed negative)."""
    by_date = {r.date: r.call_gamma + r.put_gamma for r in rows}
    return sorted(by_date.items())


def label(net):
    return protocol.NEG if net < 0 else protocol.POS


class Regime:
    """Day D's regime = the label of the last session strictly before D. Sessions are UW's own rows."""

    def __init__(self, rows):
        s = series(rows)
        self.dates = [d for d, _ in s]
        self.labels = [label(n) for _, n in s]

    def prior_index(self, d):
        i = bisect.bisect_left(self.dates, d) - 1
        return i if i >= 0 else None

    def for_day(self, d):
        i = self.prior_index(d)
        return None if i is None else self.labels[i]

    def placebo_for_day(self, d, shift=protocol.PLACEBO_SHIFT_SESSIONS):
        """The label of the session `shift` sessions before D-1 -- same base rate and persistence, wrong alignment."""
        i = self.prior_index(d)
        if i is None or i - shift < 0:
            return None
        return self.labels[i - shift]

    def episodes(self, first_day, last_day):
        """Maximal same-label runs among the D-1 sessions feeding signal days first_day..last_day."""
        i, j = self.prior_index(first_day), self.prior_index(last_day)
        if i is None or j is None:
            return {protocol.POS: 0, protocol.NEG: 0}
        return count_runs(self.labels[i:j + 1])


def count_runs(labels):
    runs = {protocol.POS: 0, protocol.NEG: 0}
    prev = None
    for lab in labels:
        if lab != prev:
            runs[lab] += 1
            prev = lab
    return runs
