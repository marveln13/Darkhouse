"""
Resumable data collection for the flow conviction study.

    python -m research.flow.collect discover [--start D --end D]
    python -m research.flow.collect enrich [--max-calls N]

Raw UW responses are cached under .cache/ (gitignored: UW data is personal-use,
never committed), so every re-run is free and an interrupted run resumes.
"""
import argparse
import json
import os
import random
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


def cmd_enrich(args, client):
    events = load_events()
    keep, sample = enrichment_targets(events)
    chains = list(dict.fromkeys(e.chain for e in keep + sample))
    print(f"{len(events)} contract-days | {len(keep)} pass the ${protocol.ENRICH_MIN_ALERT_PREMIUM:,} cutoff, "
          f"{len(sample)} leakage sample | {len(chains)} unique contracts to enrich", flush=True)
    calls = 0
    for i, chain in enumerate(chains):
        if calls >= args.max_calls:
            print(f"call budget {args.max_calls} reached after {i} contracts -- rerun to resume")
            return
        try:
            client.get(f"/api/option-contract/{chain}/historic")
        except Exception as e:
            print(f"  skip {chain}: {type(e).__name__} {str(e)[:60]}")
        calls += 1
        if i % 500 == 0:
            print(f"  {i}/{len(chains)} contracts", flush=True)
    print("enrichment done")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    d = sub.add_parser("discover")
    d.add_argument("--start", default=protocol.DISCOVERY_START)
    d.add_argument("--end", default=protocol.DISCOVERY_END)
    d.set_defaults(func=cmd_discover)
    e = sub.add_parser("enrich")
    e.add_argument("--max-calls", type=int, default=30_000)
    e.set_defaults(func=cmd_enrich)
    args = ap.parse_args()
    client = CachingClient(UnusualWhalesClient(), os.path.join(REPO_ROOT, ".cache", "uw"))
    args.func(args, client)


if __name__ == "__main__":
    load_dotenv()
    main()
