"""
Resumable data collection for the flow conviction study.

    python -m research.flow.collect discover [--start D --end D]
    python -m research.flow.collect enrich [--daily-cap 39000] [--wait-for-reset]

Raw UW responses are cached under .cache/ (gitignored: UW data is personal-use,
never committed), so every re-run is free and an interrupted run resumes.
"""
import argparse
import json
import os
import random
import time
from datetime import date as date_cls, datetime, timedelta

from dotenv import load_dotenv

from compare.argus_logs import ET, et_date
from research.caching_client import CachingClient
from research.flow import protocol
from research.flow.events import aggregate_events
from src.models import FlowAlert
from src.uw_client import UnusualWhalesClient

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(REPO_ROOT, ".cache", "flow")


def _dt(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def discover_day(client, date, page_limit=200, max_pages=40, filters=None):
    """All market-wide alerts for one ET date under the protocol filters. Verified live: the
    API ignores the lower time bound, so the pager would walk back through earlier days;
    it stops as soon as a page reaches an earlier day and keeps only `date`."""
    filters = protocol.DISCOVERY_FILTERS if filters is None else filters
    start = datetime.fromisoformat(date).replace(tzinfo=ET)
    cursor, seen, out = (start + timedelta(days=1)).isoformat(), set(), []
    for _ in range(max_pages):
        raw = client.get("/api/option-trades/flow-alerts",
                         {"limit": page_limit, "newer_than": start.isoformat(), "older_than": cursor, **filters})
        rows = raw.get("data", raw)
        for r in rows:
            key = (r["created_at"], r["option_chain"], r["total_premium"], r["total_size"])
            if key not in seen and et_date(_dt(r["created_at"])) == date:
                seen.add(key)
                dte = (date_cls.fromisoformat(r["expiry"]) - date_cls.fromisoformat(date)).days
                if protocol.DISCOVERY_DTE[0] <= dte <= protocol.DISCOVERY_DTE[1]:
                    out.append(r)
        if len(rows) < page_limit:
            break
        oldest = min(r["created_at"] for r in rows)
        if et_date(_dt(oldest)) < date or oldest == cursor:
            break
        cursor = oldest
    return out


def weekdays(start, end):
    d, last = date_cls.fromisoformat(start), date_cls.fromisoformat(end)
    while d <= last:
        if d.weekday() < 5:
            yield d.isoformat()
        d += timedelta(days=1)


def cmd_discover(args, client):
    os.makedirs(os.path.join(CACHE, "alerts"), exist_ok=True)
    done = total = 0
    for day in weekdays(args.start, args.end):
        path = os.path.join(CACHE, "alerts", f"{day}.json")
        if os.path.exists(path):
            continue
        rows = discover_day(client, day)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f)
        done += 1
        total += len(rows)
        if done % 10 == 0:
            print(f"  {day}: {done} new days, {total} alerts", flush=True)
    print(f"discovery done: {done} new days, {total} new alerts")


def load_events(start=None, end=None):
    events = []
    folder = os.path.join(CACHE, "alerts")
    for name in sorted(os.listdir(folder)):
        day = name[:-5]
        if (start and day < start) or (end and day > end):
            continue
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            events.extend(aggregate_events([FlowAlert.from_api(r) for r in json.load(f)]))
    return events


def enrichment_targets(events):
    """Events that pass the premium cutoff, plus a seeded random slice of the rest
    so the cutoff's leakage can be measured instead of assumed."""
    rng = random.Random(protocol.LEAKAGE_SEED)
    keep, sample = [], []
    for e in sorted(events, key=lambda e: (e.date, e.ticker, e.chain)):
        if e.cum_premium >= protocol.ENRICH_MIN_ALERT_PREMIUM:
            keep.append(e)
        elif rng.random() < protocol.LEAKAGE_SAMPLE_FRAC:
            sample.append(e)
    return keep, sample


def enrich_chains(client, chains, daily_cap, wait_for_reset=False, sleep=time.sleep, poll_seconds=300, log=print):
    """Fetch each contract's /historic once. Cached contracts are skipped WITHOUT counting against
    the quota. The UW daily counter (x-uw-daily-req-count) is read from the responses; at the cap it
    either stops or polls until the quota resets. Returns the number of new fetches."""
    inner, fetched = client.inner, 0
    for chain in chains:
        path = f"/api/option-contract/{chain}/historic"
        if client.peek(path) is not None:
            continue
        while inner.daily_request_count >= daily_cap:
            if not wait_for_reset:
                log(f"daily quota {inner.daily_request_count} >= cap {daily_cap} after {fetched} new fetches -- "
                    f"rerun after the reset")
                return fetched
            log(f"  quota {inner.daily_request_count}/{daily_cap}; checking again in {poll_seconds}s", )
            sleep(poll_seconds)
            try:
                inner.get(path)          # one request refreshes the counter
            except Exception:
                pass
        try:
            client.get(path)
            fetched += 1
        except Exception as e:
            log(f"  skip {chain}: {type(e).__name__} {str(e)[:60]}")
        if fetched and fetched % 500 == 0:
            log(f"  {fetched} new contracts fetched (quota {inner.daily_request_count}/{daily_cap})")
    return fetched


def cmd_enrich(args, client):
    events = load_events()
    keep, sample = enrichment_targets(events)
    chains = list(dict.fromkeys(e.chain for e in keep + sample))
    cached = sum(1 for c in chains if client.peek(f"/api/option-contract/{c}/historic") is not None)
    print(f"{len(events)} contract-days | {len(keep)} pass the ${protocol.ENRICH_MIN_ALERT_PREMIUM:,} cutoff, "
          f"{len(sample)} leakage sample | {len(chains)} unique contracts, {cached} already cached", flush=True)
    fetched = enrich_chains(client, chains, args.daily_cap, wait_for_reset=args.wait_for_reset)
    remaining = sum(1 for c in chains if client.peek(f"/api/option-contract/{c}/historic") is None)
    print(f"done: {fetched} new fetches, {remaining} contracts still missing (transient errors retry on rerun)")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    d = sub.add_parser("discover")
    d.add_argument("--start", default=protocol.DISCOVERY_START)
    d.add_argument("--end", default=protocol.DISCOVERY_END)
    d.set_defaults(func=cmd_discover)
    e = sub.add_parser("enrich")
    e.add_argument("--daily-cap", type=int, default=39_000, help="stop/wait at this UW daily request count (limit 40,000)")
    e.add_argument("--wait-for-reset", action="store_true", help="poll until the daily quota resets, then continue")
    e.set_defaults(func=cmd_enrich)
    args = ap.parse_args()
    client = UnusualWhalesClient()
    if args.command == "enrich":     # small per-contract responses; discovery has its own per-day cache
        client = CachingClient(client, os.path.join(REPO_ROOT, ".cache", "uw"))
    args.func(args, client)


if __name__ == "__main__":
    load_dotenv()
    main()
