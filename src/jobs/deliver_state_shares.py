"""Play the state side of the Delta Sharing states.

Ohio, Colorado and North Carolina already run their UI data on Databricks. Their
claim systems append every status change to a typed Delta table, which each
state shares with US DOL ETA. This task commits the pending batch weeks of
status changes to those tables; DOL picks them up from the change feed.
"""

import argparse
import sys

from pyspark.sql import SparkSession
from pyspark.sql import functions as F

parser = argparse.ArgumentParser()
parser.add_argument("--catalog", default="lanl")
parser.add_argument("--schema", default="dol_ui")
parser.add_argument("--specs_path", default="", help="Directory containing state_specs.py")
parser.add_argument("--hold_back", type=int, default=0, help="Leave the newest N batch weeks uncommitted")
args, _ = parser.parse_known_args()

if args.specs_path:
    sys.path.insert(0, args.specs_path)
from state_specs import SHARE_STATES, STATE_SPECS, share_columns, share_staged_table  # noqa: E402

spark = SparkSession.builder.getOrCreate()
ns = f"{args.catalog}.{args.schema}"

for state in SHARE_STATES:
    table = share_staged_table(args.catalog, state)
    cols = share_columns(state)
    payload_schema = ", ".join(f"{c} {t}" for c, t in cols[1:-1])
    pending = (
        spark.table(f"{ns}.ref_state_share_outbox")
        .where(F.col("state_code") == state)
        .join(spark.table(table).select("event_id"), "event_id", "left_anti")
        .withColumn("status_changed_at", F.timestamp_micros("event_ts_unix_us"))
        .withColumn("batch_week", F.expr("date_add(to_date(status_changed_at), 6 - weekday(to_date(status_changed_at)))"))
        .withColumn("r", F.from_json("payload", payload_schema))
        .select("event_id", "r.*", "status_changed_at", "batch_week")
    )
    weeks = sorted(r.batch_week for r in pending.select("batch_week").distinct().collect())
    if args.hold_back:
        weeks = weeks[:-args.hold_back]
    if weeks:
        pending.where(F.col("batch_week") <= weeks[-1]).select(*[c for c, _ in cols]).write.mode("append").saveAsTable(table)
    version = spark.sql(f"DESCRIBE HISTORY {table} LIMIT 1").first().version
    print(f"{STATE_SPECS[state]['name']}: committed {len(weeks)} batch weeks to {table} (now at version {version})")
