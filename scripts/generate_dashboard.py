#!/usr/bin/env python3
"""
Generates the weekly connectivity dashboard data for the Yango power bank fleet.

What it does
------------
1. Finds the CSV export to use (latest file in data/, or an explicit --csv path).
2. Figures out which week to report on: the most recently COMPLETED Monday-Sunday
   week in America/Bogota time, unless --week-start is given explicitly.
3. Excludes any station sitting in the warehouse (not yet deployed to a location).
4. For every remaining station, computes % connectivity for that week from its
   Disconnections history, handling:
     - stations created partway through the week (prorated denominator)
     - stations with zero disconnection events but a live "not_responding"
       status (the "0% connected / blind spot" bucket - likely dead the whole
       observed period, just never logged a reconnect event)
5. Writes docs/data/latest.json (what the live dashboard reads) and archives a
   dated copy under docs/data/history/.

Usage
-----
    python3 scripts/generate_dashboard.py
    python3 scripts/generate_dashboard.py --csv data/vendings_2026-08-24.csv
    python3 scripts/generate_dashboard.py --week-start 2026-08-10   # backfill a specific week
"""

import argparse
import csv
import glob
import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BOG = ZoneInfo("America/Bogota")

# Station rows whose PlaceName matches one of these are inventory sitting in
# the warehouse, not a real deployment - excluded from the dashboard entirely.
# Add to this set if new warehouse/staging locations show up in future exports.
WAREHOUSE_PLACENAMES = {"@Bogota office"}

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO_ROOT, "data")
OUT_DIR = os.path.join(REPO_ROOT, "docs", "data")
HISTORY_DIR = os.path.join(OUT_DIR, "history")


def parse_ts(ts):
    return datetime.fromisoformat(ts)


def find_latest_csv():
    candidates = sorted(glob.glob(os.path.join(DATA_DIR, "*.csv")))
    if not candidates:
        sys.exit(f"No CSV files found in {DATA_DIR}. Add one or pass --csv.")
    return candidates[-1]


def last_completed_week(now_bog):
    """Most recently finished Monday 00:00 -> next Monday 00:00 window."""
    this_monday = (now_bog - timedelta(days=now_bog.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    week_start = this_monday - timedelta(days=7)
    week_end = this_monday
    return week_start, week_end


def merge_intervals(intervals):
    intervals = sorted(intervals)
    merged = []
    for s, e in intervals:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="Path to the vendings CSV export to use")
    ap.add_argument(
        "--week-start",
        help="YYYY-MM-DD (a Monday) to backfill a specific week instead of the last completed one",
    )
    args = ap.parse_args()

    csv_path = args.csv or find_latest_csv()
    now = datetime.now(tz=BOG)

    if args.week_start:
        week_start = datetime.strptime(args.week_start, "%Y-%m-%d").replace(tzinfo=BOG)
        week_end = week_start + timedelta(days=7)
    else:
        week_start, week_end = last_completed_week(now)

    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    warehouse_count = sum(1 for r in rows if r["PlaceName"].strip() in WAREHOUSE_PLACENAMES)
    rows = [r for r in rows if r["PlaceName"].strip() not in WAREHOUSE_PLACENAMES]

    results = []
    not_yet_created = 0

    for r in rows:
        loc_created = parse_ts(r["LocationCreatedAt"]).astimezone(BOG)
        effective_start = max(week_start, loc_created)
        if effective_start >= week_end:
            not_yet_created += 1
            continue

        denom_hours = (week_end - effective_start).total_seconds() / 3600
        events = json.loads(r["Disconnections"])
        status = r["Status"]

        if len(events) == 0 and status == "not_responding":
            category = "0_connection"
            pct = 0.0
        else:
            intervals = []
            for ev in events:
                ds = ev.get("disconnection_time")
                cs = ev.get("connection_time")
                if not ds:
                    continue
                s = parse_ts(ds).astimezone(BOG)
                e = parse_ts(cs).astimezone(BOG) if cs else now
                clip_s, clip_e = max(s, effective_start), min(e, week_end)
                if clip_e > clip_s:
                    intervals.append((clip_s, clip_e))
            merged = merge_intervals(intervals)
            down_h = sum((e - s).total_seconds() for s, e in merged) / 3600
            up_h = denom_hours - down_h
            pct = (up_h / denom_hours * 100) if denom_hours > 0 else 0.0
            category = "green" if pct > 50 else ("yellow" if pct > 25 else "red")

        results.append(
            {
                "display": r["DisplayNumber"],
                "parkId": r["ParkID"],
                "place": r["PlaceName"].strip() or "(no name)",
                "address": r["Address"].strip() or "(no address)",
                "category": category,
                "pct": round(pct, 1),
                "days": (week_end - loc_created).days,
            }
        )

    cat_order = {"0_connection": 0, "red": 1, "yellow": 2, "green": 3}
    results.sort(key=lambda r: (cat_order[r["category"]], r["pct"], -r["days"]))

    counts = {c: 0 for c in cat_order}
    for r in results:
        counts[r["category"]] += 1

    payload = {
        "generated_at": now.isoformat(),
        "week_start": week_start.date().isoformat(),
        "week_end": (week_end - timedelta(days=1)).date().isoformat(),
        "source_csv": os.path.basename(csv_path),
        "warehouse_excluded": warehouse_count,
        "not_yet_deployed_this_week": not_yet_created,
        "counts": counts,
        "stations": results,
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(HISTORY_DIR, exist_ok=True)

    with open(os.path.join(OUT_DIR, "latest.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    history_path = os.path.join(HISTORY_DIR, f"{payload['week_start']}.json")
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    # Keep a manifest of available weeks so the dashboard can offer a week picker later.
    manifest_path = os.path.join(OUT_DIR, "weeks.json")
    weeks = set()
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            weeks = set(json.load(f))
    weeks.add(payload["week_start"])
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(sorted(weeks, reverse=True), f)

    print(f"Week {payload['week_start']} to {payload['week_end']}: "
          f"{len(results)} stations categorized, {warehouse_count} warehouse excluded, "
          f"{not_yet_created} not yet deployed that week.")
    print(f"Counts: {counts}")


if __name__ == "__main__":
    main()
