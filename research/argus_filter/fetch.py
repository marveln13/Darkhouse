"""
Step 2 of the implementation checklist: the quota-aware, resumable UW fetch for the ARGUS-filter study.

    python -m research.argus_filter.fetch --dry-run        # plan + cache coverage, no API calls
    python -m research.argus_filter.fetch                  # spends quota -- run only when the study is go

Reads ONLY signal_keys.csv (ticker, date, prior_date, entry_ts): this module never imports the outcome
loader, so it cannot see R. For every unique (ticker, D-1) it fetches two endpoints -- dark-pool price levels
and GEX levels -- in a seeded random order (PREREGISTRATION.md, "Data plan and quota") until the budget is
spent: at most DAILY_REQUEST_CAP requests per UW quota day (x-uw-daily-req-count; the day resets at 8 PM ET)
and at most MAX_QUOTA_DAYS quota days. The order is random, so whatever completes is a random sample.

Raw responses go through CachingClient into the gitignored .cache/uw/ (UW terms: personal use), so a re-run
never re-spends quota. Permanent client errors (4xx other than auth/rate-limit) are remembered in
fetch_state.json so they are not retried; auth failures abort without recording anything.
"""
import argparse
import json
import os
import random
from collections import Counter
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

from compare.argus_logs import ET
from research.argus_filter import levels, protocol
from research.argus_filter.signals import CACHE_DIR, REPO_ROOT, fetch_plan, load_calendar, load_keys
from research.caching_client import CachingClient
from src.uw_client import UnusualWhalesClient

UW_CACHE_DIR = os.path.join(REPO_ROOT, ".cache", "uw")


def quota_day_key(now):
    """Label of the UW quota day `now` falls in. The quota resets at 8 PM ET, so the day is keyed by the date
    of the most recent reset: 19:59 ET on 9/20 is day 2026-09-19, 20:00 ET on 9/20 is day 2026-09-20."""
    return (now.astimezone(ET) - timedelta(hours=protocol.QUOTA_RESET_HOUR_ET)).date().isoformat()


def fetch_order(pairs, seed=protocol.SEED):
    """Seeded random order over the unique pairs; independent of the order the pairs arrive in."""
    ordered = sorted(set(pairs))
    random.Random(seed).shuffle(ordered)
    return ordered


def load_state(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"quota_days": {}, "permanent": {}}


def save_state(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    os.replace(tmp, path)


def coverage(pairs, client, state):
    """(cached endpoints, permanently failed endpoints, endpoints still to fetch) over `pairs`. No API calls."""
    cached = failed = todo = 0
    for ticker, d in pairs:
        for _, path, params in levels.requests_for(ticker, d):
            if client.peek(path, params) is not None:
                cached += 1
            elif f"{path}|{d}" in state["permanent"]:
                failed += 1
            else:
                todo += 1
    return cached, failed, todo


def run_fetch(pairs, client, state, persist, daily_cap=protocol.DAILY_REQUEST_CAP,
              max_quota_days=protocol.MAX_QUOTA_DAYS, now=lambda: datetime.now(ET), log=print):
    """Fetch until the budget is spent. `client` is a CachingClient (peek/get, .inner.daily_request_count).
    Returns a Counter of outcomes with a "stop" key describing why the run ended."""
    inner, stats, day = client.inner, Counter(), None
    stop = "complete"
    for ticker, d in fetch_order(pairs):
        for _, path, params in levels.requests_for(ticker, d):
            key = f"{path}|{d}"
            if client.peek(path, params) is not None:
                stats["cached"] += 1
                continue
            if key in state["permanent"]:
                stats["permanent_skipped"] += 1
                continue

            today = quota_day_key(now())
            if today != day:                      # first request of a new quota day (or of this run)
                if today not in state["quota_days"] and len(state["quota_days"]) >= max_quota_days:
                    return _finish(stats, "quota_days_exhausted", persist, state)
                state["quota_days"].setdefault(today, {"requests": 0})
                if day is not None:
                    inner.daily_request_count = 0  # the server counter reset; the next response refreshes it
                day = today
            if inner.daily_request_count >= daily_cap:
                return _finish(stats, "daily_cap", persist, state)

            state["quota_days"][day]["requests"] += 1
            try:
                client.get(path, params)
                stats["fetched"] += 1
            except requests.HTTPError as e:
                code = e.response.status_code if e.response is not None else None
                if code in (401, 403):
                    persist(state)
                    raise
                if code == 429:
                    return _finish(stats, "rate_limited", persist, state)
                if code is not None and 400 <= code < 500:
                    state["permanent"][key] = code
                    stats["permanent_new"] += 1
                else:
                    stats["transient"] += 1
            except (requests.ConnectionError, requests.Timeout, ValueError):
                stats["transient"] += 1            # not recorded: retried on the next run
            if stats["fetched"] and stats["fetched"] % 500 == 0:
                log(f"  {stats['fetched']} fetched (quota {inner.daily_request_count}/{daily_cap}, day {day})")
                persist(state)
    return _finish(stats, stop, persist, state)


def _finish(stats, stop, persist, state):
    stats["stop"] = stop
    persist(state)
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="show the plan and cache coverage; make no API calls")
    ap.add_argument("--daily-cap", type=int, default=protocol.DAILY_REQUEST_CAP)
    ap.add_argument("--cache-dir", default=CACHE_DIR)
    args = ap.parse_args()
    if args.daily_cap > protocol.DAILY_REQUEST_CAP:
        ap.error(f"--daily-cap may not exceed the registered {protocol.DAILY_REQUEST_CAP}")

    pairs = fetch_plan(load_keys(args.cache_dir), load_calendar(args.cache_dir))
    state_path = os.path.join(args.cache_dir, protocol.FETCH_STATE_FILE)
    state = load_state(state_path)
    if args.dry_run:
        client = CachingClient(None, UW_CACHE_DIR)          # peek only; no UW client, no key needed
        cached, failed, todo = coverage(pairs, client, state)
        print(f"{len(pairs)} unique (ticker, D-1) pairs = {2 * len(pairs)} endpoint requests")
        print(f"  already cached: {cached} | permanent failures on record: {failed} | still to fetch: {todo}")
        print(f"  quota days used so far: {len(state['quota_days'])}/{protocol.MAX_QUOTA_DAYS} | "
              f"days needed for the rest at {args.daily_cap}/day: {-(-todo // args.daily_cap)}")
        return

    client = CachingClient(UnusualWhalesClient(), UW_CACHE_DIR)
    stats = run_fetch(pairs, client, state, lambda s: save_state(state_path, s), daily_cap=args.daily_cap)
    print(f"stopped: {stats['stop']} | {dict((k, v) for k, v in stats.items() if k != 'stop')}")
    cached, failed, todo = coverage(pairs, client, state)
    print(f"coverage: {cached} cached, {failed} permanent failures, {todo} still to fetch "
          f"(quota days used {len(state['quota_days'])}/{protocol.MAX_QUOTA_DAYS})")


if __name__ == "__main__":
    load_dotenv()
    main()
