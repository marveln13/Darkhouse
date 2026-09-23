from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
import requests

from research.argus_filter import fetch, levels, protocol
from research.caching_client import CachingClient
from src import darkpool, gex

ET = ZoneInfo("America/New_York")
PAIRS = [(f"T{i:02d}", "2026-09-08") for i in range(30)]


def http_error(code):
    resp = requests.Response()
    resp.status_code = code
    return requests.HTTPError(f"{code}", response=resp)


class FakeInner:
    """Stands in for UnusualWhalesClient: counts every request like x-uw-daily-req-count would."""

    def __init__(self, errors=None):
        self.daily_request_count = 0
        self.calls = []
        self.errors = errors or {}                 # {(path, date): exception or list of exceptions (consumed in order)}

    def get(self, path, params=None):
        self.calls.append((path, params))
        self.daily_request_count += 1
        err = self.errors.get((path, params.get("date")))
        if isinstance(err, list):
            err = err.pop(0) if err else None
        if err is not None:
            raise err
        return {"date": params.get("date"), "data": [{"price": "100", "dark_pool_volume": 1, "regular_volume": 1}]}


def setup(tmp_path, errors=None):
    inner = FakeInner(errors)
    state = {"quota_days": {}, "permanent": {}}
    return inner, CachingClient(inner, str(tmp_path / "uw")), state


def run(pairs, client, state, now=None, **kw):
    kw.setdefault("log", lambda *_: None)
    return fetch.run_fetch(pairs, client, state, lambda s: None,
                           now=now or (lambda: datetime(2026, 9, 21, 10, 0, tzinfo=ET)), **kw)


# ---- order ----

def test_order_is_seeded_random_and_independent_of_input_order():
    a = fetch.fetch_order(PAIRS)
    assert a == fetch.fetch_order(list(reversed(PAIRS)))          # arrival order does not matter
    assert a == fetch.fetch_order(PAIRS + PAIRS[:5])              # duplicates collapse
    assert sorted(a) == PAIRS and a != PAIRS                      # a permutation, and not the sorted order
    assert a != fetch.fetch_order(PAIRS, seed=protocol.SEED + 1)  # the registered seed is what fixes it


# ---- requests ----

def test_each_pair_fetches_exactly_the_two_endpoints_the_analysis_reads(tmp_path):
    inner, client, state = setup(tmp_path)
    stats = run([("AAA", "2026-09-08")], client, state)
    assert stats["fetched"] == 2 and stats["stop"] == "complete"
    assert sorted(inner.calls, key=lambda c: c[0]) == sorted([levels.dp_request("AAA", "2026-09-08"),
                                                              levels.gex_request("AAA", "2026-09-08")], key=lambda c: c[0])


def test_request_helpers_match_the_src_wrappers_so_fetch_and_analysis_share_a_cache_key():
    class Recorder:
        def __init__(self):
            self.calls = []

        def get(self, path, params=None):
            self.calls.append((path, params))
            return {"date": "2026-09-08", "data": [] if "price-levels" in path else {"gamma_flip": "100"}}

    rec = Recorder()
    darkpool.price_levels(rec, "AAA", date="2026-09-08")
    gex.gex_levels(rec, "AAA", date="2026-09-08", source=protocol.GEX_SOURCE)
    assert rec.calls == [levels.dp_request("AAA", "2026-09-08"), levels.gex_request("AAA", "2026-09-08")]


def test_cached_endpoints_are_skipped_and_do_not_count_against_the_quota(tmp_path):
    inner, client, state = setup(tmp_path)
    run(PAIRS[:4], client, state)                                  # 8 real requests, now cached
    inner.calls.clear()
    inner.daily_request_count = 0
    stats = run(PAIRS[:6], client, state)                          # 4 pairs cached, 2 new
    assert stats["cached"] == 8 and stats["fetched"] == 4 and len(inner.calls) == 4


# ---- budget ----

def test_daily_cap_stops_the_run_and_a_rerun_resumes_without_repeating_requests(tmp_path):
    inner, client, state = setup(tmp_path)
    stats = run(PAIRS, client, state, daily_cap=5)
    assert stats["stop"] == "daily_cap" and stats["fetched"] == 5 and inner.daily_request_count == 5

    inner.daily_request_count = 0                                   # the next quota day
    total = 5
    while True:
        stats = run(PAIRS, client, state, daily_cap=5)
        total += stats["fetched"]
        inner.daily_request_count = 0
        if stats["stop"] == "complete":
            break
    assert total == 2 * len(PAIRS) == len(inner.calls)              # every endpoint fetched exactly once


def test_the_cap_is_checked_before_every_single_request(tmp_path):
    inner, client, state = setup(tmp_path)
    inner.daily_request_count = protocol.DAILY_REQUEST_CAP - 1      # one request of headroom left today
    stats = run(PAIRS, client, state)
    assert stats["fetched"] == 1 and inner.daily_request_count == protocol.DAILY_REQUEST_CAP


# ---- quota days ----

def test_quota_day_rolls_over_at_8pm_et():
    assert fetch.quota_day_key(datetime(2026, 9, 20, 19, 59, 59, tzinfo=ET)) == "2026-09-19"
    assert fetch.quota_day_key(datetime(2026, 9, 20, 20, 0, 0, tzinfo=ET)) == "2026-09-20"
    assert fetch.quota_day_key(datetime(2026, 9, 21, 9, 0, tzinfo=ET)) == "2026-09-20"
    assert fetch.quota_day_key(datetime(2026, 9, 21, 9, 0, tzinfo=ZoneInfo("UTC"))) == "2026-09-20"   # 05:00 ET


def test_a_fourth_quota_day_is_refused_and_makes_no_requests(tmp_path):
    inner, client, state = setup(tmp_path)
    state["quota_days"] = {"2026-09-17": {"requests": 1}, "2026-09-18": {"requests": 1}, "2026-09-19": {"requests": 1}}
    stats = run(PAIRS, client, state)                               # now = 09-21 10:00 ET -> quota day 09-20
    assert stats["stop"] == "quota_days_exhausted" and inner.calls == []

    state["quota_days"].pop("2026-09-17")                           # a day that is already on record is allowed
    state["quota_days"]["2026-09-20"] = {"requests": 3}
    assert run(PAIRS[:1], client, state)["stop"] == "complete"


def test_requests_are_counted_per_quota_day_and_a_reset_mid_run_clears_the_counter(tmp_path):
    inner, client, state = setup(tmp_path)
    clock = iter([datetime(2026, 9, 21, 19, 59, tzinfo=ET)] * 2 + [datetime(2026, 9, 21, 20, 1, tzinfo=ET)] * 200)
    inner.daily_request_count = protocol.DAILY_REQUEST_CAP - 2      # nearly out today
    stats = run(PAIRS[:5], client, state, now=lambda: next(clock))
    # 2 requests use up day 09-20; the reset at 8 PM opens day 09-21 with a fresh counter and the run continues
    assert stats["stop"] == "complete" and stats["fetched"] == 10
    assert state["quota_days"]["2026-09-20"]["requests"] == 2 and state["quota_days"]["2026-09-21"]["requests"] == 8


# ---- errors ----

def test_permanent_client_errors_are_recorded_and_never_retried(tmp_path):
    path, params = levels.dp_request("AAA", "2026-09-08")
    inner, client, state = setup(tmp_path, {(path, "2026-09-08"): http_error(404)})
    stats = run([("AAA", "2026-09-08")], client, state)
    assert stats["permanent_new"] == 1 and state["permanent"] == {f"{path}|2026-09-08": 404}
    inner.calls.clear()
    stats = run([("AAA", "2026-09-08")], client, state)
    assert stats["permanent_skipped"] == 1 and inner.calls == []


def test_transient_errors_are_not_recorded_and_are_retried_next_run(tmp_path):
    path, _ = levels.dp_request("AAA", "2026-09-08")
    inner, client, state = setup(tmp_path, {(path, "2026-09-08"): [http_error(503)]})   # fails once, then works
    stats = run([("AAA", "2026-09-08")], client, state)
    assert stats["transient"] == 1 and state["permanent"] == {}
    stats = run([("AAA", "2026-09-08")], client, state)
    assert stats["fetched"] == 1 and stats["cached"] == 1            # the retried endpoint succeeded


def test_connection_errors_and_timeouts_are_transient(tmp_path):
    path, _ = levels.gex_request("AAA", "2026-09-08")
    inner, client, state = setup(tmp_path, {(path, "2026-09-08"): [requests.ConnectionError("x")]})
    assert run([("AAA", "2026-09-08")], client, state)["transient"] == 1 and state["permanent"] == {}


@pytest.mark.parametrize("code", [401, 403])
def test_an_auth_failure_aborts_and_is_never_recorded_as_missing_data(tmp_path, code):
    path, _ = levels.dp_request("AAA", "2026-09-08")
    inner, client, state = setup(tmp_path, {(path, "2026-09-08"): http_error(code)})
    with pytest.raises(requests.HTTPError):
        run([("AAA", "2026-09-08")], client, state)
    assert state["permanent"] == {}


def test_a_rate_limit_stops_the_run_without_recording_anything(tmp_path):
    path, _ = levels.dp_request("AAA", "2026-09-08")
    inner, client, state = setup(tmp_path, {(path, "2026-09-08"): http_error(429)})
    stats = run([("AAA", "2026-09-08")], client, state)
    assert stats["stop"] == "rate_limited" and state["permanent"] == {}


def test_coverage_counts_cached_failed_and_pending_endpoints_without_any_request(tmp_path):
    inner, client, state = setup(tmp_path)
    run(PAIRS[:2], client, state)                                    # 4 cached
    dp_path, _ = levels.dp_request(PAIRS[2][0], PAIRS[2][1])
    state["permanent"][f"{dp_path}|{PAIRS[2][1]}"] = 404             # 1 failed
    inner.calls.clear()
    assert fetch.coverage(PAIRS[:4], client, state) == (4, 1, 3)     # 3 still to fetch (1 of pair 3 + both of pair 4)
    assert inner.calls == []
