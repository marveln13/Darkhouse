import numpy as np
import pytest

from research.flow import outcomes, protocol, stats

CAL = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-08", "2026-09-09", "2026-09-10",
       "2026-09-11", "2026-09-14"]          # 09-07 (Labor Day) is not a trading day
CAL, IDX = outcomes.calendar_index({d: 1.0 for d in CAL})


# ---- outcomes ----

def test_shift_counts_trading_days_not_calendar_days():
    assert outcomes.shift(CAL, IDX, "2026-09-04", 1) == "2026-09-08"       # skips the holiday weekend
    assert outcomes.shift(CAL, IDX, "2026-09-04", 5) == "2026-09-14"
    assert outcomes.shift(CAL, IDX, "2026-09-14", 1) is None                # past the calendar's end


def test_underlying_outcome_is_direction_signed_and_net_of_spy():
    closes = {"2026-09-01": 100.0, "2026-09-08": 110.0}                     # +10% over 5 trading days
    spy = {"2026-09-01": 100.0, "2026-09-08": 103.0}                        # market +3%
    assert outcomes.underlying_outcome("2026-09-01", +1, closes, spy, CAL, IDX, horizon=4) == pytest.approx(0.07)
    assert outcomes.underlying_outcome("2026-09-01", -1, closes, spy, CAL, IDX, horizon=4) == pytest.approx(-0.07)
    assert outcomes.underlying_outcome("2026-09-01", +1, {}, spy, CAL, IDX, horizon=4) is None


def _rows(entry_open=2.0, exit_avg=3.0, bid=1.9, ask=2.1):
    return {"2026-09-01": {"nbbo_bid": str(bid), "nbbo_ask": str(ask), "open_price": "1", "avg_price": "1"},
            "2026-09-02": {"open_price": str(entry_open), "avg_price": "2.5"},
            "2026-09-10": {"open_price": "9", "avg_price": str(exit_avg)}}      # D+6: five trading days after the D+1 entry


def test_contract_outcome_gross_and_net_of_the_half_spread():
    out = outcomes.contract_outcome("2026-09-01", _rows(), CAL, IDX)

    assert out["status"] == "ok" and out["gross"] == pytest.approx(0.5)
    hs = (2.1 - 1.9) / (2.1 + 1.9)
    assert out["half_spread"] == pytest.approx(hs)
    assert out["net"] == pytest.approx(3.0 * (1 - hs) / (2.0 * (1 + hs)) - 1)
    assert out["net"] < out["gross"]


def test_contract_outcome_statuses():
    assert outcomes.contract_outcome("2026-09-01", {}, CAL, IDX)["status"] == "no_row"
    assert outcomes.contract_outcome("2026-09-14", _rows(), CAL, IDX)["status"] == "no_calendar"
    assert outcomes.contract_outcome("2026-09-01", _rows(entry_open=0.05), CAL, IDX)["status"] == "sub_dime"
    at_floor = outcomes.contract_outcome("2026-09-01", _rows(entry_open=protocol.MIN_ENTRY_PRICE), CAL, IDX)
    assert at_floor["status"] == "ok"                                        # the floor itself is allowed


def test_a_crossed_or_missing_nbbo_leaves_net_unreported_but_keeps_gross():
    crossed = outcomes.contract_outcome("2026-09-01", _rows(bid=2.2, ask=2.0), CAL, IDX)
    assert crossed["status"] == "ok" and crossed["net"] is None and crossed["gross"] == pytest.approx(0.5)


# ---- stats ----

def _synthetic(effect, n_days=60, per_day=12, seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(n_days):
        for _ in range(per_day):
            bucket = rng.choice(["low", "mid", "high"])
            score = {"low": rng.integers(0, 4), "mid": rng.integers(4, 7), "high": rng.integers(7, 10)}[bucket]
            base = effect * {"low": 0, "mid": 0.5, "high": 1}[bucket]
            rows.append({"date": f"2026-{1 + d // 28:02d}-{1 + d % 28:02d}", "bucket": bucket, "score": int(score),
                         "y": float(base + rng.normal(0, 1))})
    return rows


def test_winsorize_clips_the_tails_at_the_registered_quantiles():
    w = stats.winsorize(list(range(100)) + [10_000])
    assert w.max() < 200 and w.min() >= 0


def test_a_real_effect_is_detected_by_every_test():
    rows = _synthetic(effect=0.6)
    assert stats.high_minus_low(rows, "y") > 0.3
    assert stats.spearman(rows, "y") > 0.15
    boot = stats.cluster_bootstrap(rows, "y", n=400)
    assert boot["lo"] > 0 and boot["p_two_sided"] < 0.05
    assert stats.permutation_test(rows, "y", n=300)["p_two_sided"] < 0.05


def test_a_null_effect_is_not_called_significant():
    rows = _synthetic(effect=0.0, seed=7)
    boot = stats.cluster_bootstrap(rows, "y", n=400)
    assert boot["lo"] < 0 < boot["hi"]
    assert stats.permutation_test(rows, "y", n=300)["p_two_sided"] > 0.05


def test_half_split_reports_each_half_separately():
    rows = _synthetic(effect=0.8)
    split = stats.half_split(rows, "y")
    assert split["first_half"] > 0 and split["second_half"] > 0


def test_bucket_table_counts_and_hit_rates():
    rows = [{"date": "d1", "bucket": "high", "score": 8, "y": 1.0}, {"date": "d2", "bucket": "high", "score": 8, "y": -1.0},
            {"date": "d3", "bucket": "low", "score": 1, "y": None}]
    table = stats.bucket_table(rows, "y")
    assert table["high"]["n"] == 2 and table["high"]["hit_rate"] == 0.5
    assert table["low"]["n"] == 0 and table["low"]["mean_w"] is None       # a missing outcome is not silently a zero


def test_spearman_handles_ties_and_perfect_monotone_relations():
    rows = [{"date": "d", "bucket": "low", "score": s, "y": float(s) * 2} for s in (1, 2, 2, 3, 5)]
    assert stats.spearman(rows, "y") == pytest.approx(1.0)
