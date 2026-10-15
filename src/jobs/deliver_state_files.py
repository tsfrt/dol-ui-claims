"""Deliver batch extract files for states that send files instead of streaming.

Michigan's UIA does not push events; it publishes a weekly CSV extract from
MiWAM to a drop location. This task plays the state's side: it writes one file
per batch week into the Unity Catalog volume that Auto Loader watches.
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from pyspark.sql import SparkSession

parser = argparse.ArgumentParser()
parser.add_argument("--catalog", default="lanl")
parser.add_argument("--schema", default="dol_ui")
parser.add_argument("--volume", default="state_drops")
parser.add_argument("--specs_path", default="", help="Directory containing state_specs.py")
parser.add_argument("--hold_back", type=int, default=0, help="Leave the newest N batch files undelivered")
args, _ = parser.parse_known_args()

if args.specs_path:
    sys.path.insert(0, args.specs_path)
from state_specs import FILE_DROP_STATES, STATE_SPECS, file_columns  # noqa: E402

spark = SparkSession.builder.getOrCreate()
ns = f"{args.catalog}.{args.schema}"
root = f"/Volumes/{args.catalog}/{args.schema}/{args.volume}"


def batch_week(ts_us):
    d = datetime.fromtimestamp(ts_us / 1_000_000, tz=timezone.utc).date()
    return d + timedelta(days=6 - d.weekday())


for state in FILE_DROP_STATES:
    rows = spark.sql(f"SELECT event_id, event_ts_unix_us, payload FROM {ns}.ref_state_file_outbox WHERE state_code = '{state}'").collect()
    batches = {}
    for r in rows:
        batches.setdefault(batch_week(r.event_ts_unix_us), []).append(r)
    weeks = sorted(batches)
    if args.hold_back:
        weeks = weeks[:-args.hold_back]
    folder = f"{root}/{state.lower()}"
    os.makedirs(folder, exist_ok=True)
    cols = file_columns(state)
    written = 0
    for wk in weeks:
        path = f"{folder}/{state}_UIA_CLAIMS_{wk:%Y%m%d}.csv"
        if os.path.exists(path):
            continue
        tmp = f"{folder}/_{wk:%Y%m%d}.tmp"
        with open(tmp, "w", newline="") as fh:
            out = csv.writer(fh)
            out.writerow(cols)
            for r in sorted(batches[wk], key=lambda r: r.event_ts_unix_us):
                p = json.loads(r.payload)
                ts = datetime.fromtimestamp(r.event_ts_unix_us / 1_000_000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
                out.writerow([r.event_id, ts] + [p.get(c, "") for c in cols[2:]])
        os.rename(tmp, path)
        written += 1
    pending = len(batches) - len(weeks)
    print(f"{STATE_SPECS[state]['name']}: wrote {written} new batch files to {folder} ({pending} held back)")
