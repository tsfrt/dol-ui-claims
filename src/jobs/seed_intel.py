# Databricks notebook source
# MAGIC %md
# MAGIC ## Seed claimants, state outboxes, and federal intel
# MAGIC Generates the synthetic population, writes federal intel analogs, and (re)creates the
# MAGIC Zerobus landing table `bronze_claim_events` with grants for the producer service principal.

# COMMAND ----------

# MAGIC %pip install -q faker

# COMMAND ----------

import os
import sys

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.abspath(os.path.join(os.getcwd(), "..", "pipelines")))

from state_specs import FILE_DROP_STATES, SHARE_STATES, STATE_SPECS, share_columns, share_staged_table
from synthetic import generate

dbutils.widgets.text("catalog", "lanl")
dbutils.widgets.text("schema", "dol_ui")
dbutils.widgets.text("n_applicants", "4000")
dbutils.widgets.text("zerobus_principal", "")
dbutils.widgets.text("reset_landing", "true")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
n_applicants = int(dbutils.widgets.get("n_applicants"))
producer = dbutils.widgets.get("zerobus_principal")
reset_landing = dbutils.widgets.get("reset_landing").lower() == "true"
ns = f"{catalog}.{schema}"

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {ns}")
data = generate(n_applicants=n_applicants)


def write(name, rows):
    df = spark.createDataFrame(rows)
    try:
        df.write.mode("overwrite").saveAsTable(f"{ns}.{name}")
    except Exception as e:
        print(f"{name}: schema changed, replacing ({str(e)[:120]})")
        df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{ns}.{name}")
    print(f"{name}: {len(rows):,} rows")


write("ref_applicants", data["applicants"])
write("ref_state_programs", data["ref_state_programs"])
for name in ("intel_ndnh_quarterly_wages", "intel_ssa_death_master", "intel_bop_inmates", "intel_ssa_identity", "intel_treasury_dnp", "intel_bls_laus"):
    write(name, data[name])
write("ref_state_outbox", [e for e in data["events"] if e["state_code"] not in FILE_DROP_STATES + SHARE_STATES])
write("ref_state_file_outbox", [e for e in data["events"] if e["state_code"] in FILE_DROP_STATES])
write("ref_state_share_outbox", [e for e in data["events"] if e["state_code"] in SHARE_STATES])

# Each Delta Sharing state keeps its claim status log in its own Databricks environment. Until the
# shares are mounted, those tables are staged in per-state schemas of this catalog.
for state in SHARE_STATES:
    spec = STATE_SPECS[state]
    table = share_staged_table(catalog, state)
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{spec['share']['schema']} COMMENT 'Stand-in for the {spec['agency']} Databricks workspace (Delta Sharing provider)'")
    if reset_landing:
        spark.sql(f"DROP TABLE IF EXISTS {table}")
    cols = ",\n  ".join(f"{c} {t}" for c, t in share_columns(state))
    spark.sql(f"""
      CREATE TABLE IF NOT EXISTS {table} (
        {cols}
      )
      CLUSTER BY (status_changed_at)
      COMMENT '{spec['agency']} UI claim status log, shared with US DOL ETA as {spec['share']['name']}'
      TBLPROPERTIES (delta.enableChangeDataFeed = true)
    """)

spark.sql(f"CREATE VOLUME IF NOT EXISTS {ns}.state_drops COMMENT 'Batch extract drop zone for states that deliver files instead of streaming'")
if reset_landing:
    for state in FILE_DROP_STATES:
        try:
            dbutils.fs.rm(f"/Volumes/{catalog}/{schema}/state_drops/{state.lower()}", True)
        except Exception as e:
            print(f"No previous {state} drops to clear: {e}")

for legacy in ("intel_ssa_death", "intel_inmate", "intel_ndnh_wages", "intel_sam_exclusion", "intel_ofac_sdn", "ref_claim_events", "ref_pending_push"):
    spark.sql(f"DROP TABLE IF EXISTS {ns}.{legacy}")

# COMMAND ----------

landing = f"{ns}.bronze_claim_events"
if reset_landing:
    spark.sql(f"DROP TABLE IF EXISTS {landing}")
spark.sql(f"""
  CREATE TABLE IF NOT EXISTS {landing} (
    event_id STRING COMMENT 'State-assigned event identifier',
    state_code STRING COMMENT 'Two-letter state code of the sending agency',
    agency STRING COMMENT 'Sending state workforce agency',
    event_ts TIMESTAMP COMMENT 'When the claim event occurred in the state system',
    ingested_at TIMESTAMP COMMENT 'When the producer wrote the record through Zerobus',
    payload STRING COMMENT 'Raw state-specific JSON payload'
  )
  USING DELTA
  CLUSTER BY (state_code)
  COMMENT 'Zerobus landing table for state UI claim status events'
""")
if producer:
    spark.sql(f"GRANT USE CATALOG ON CATALOG {catalog} TO `{producer}`")
    spark.sql(f"GRANT USE SCHEMA ON SCHEMA {ns} TO `{producer}`")
    spark.sql(f"GRANT SELECT, MODIFY ON TABLE {landing} TO `{producer}`")
print(f"Seeded {len(data['applicants']):,} applicants and {len(data['events']):,} outbox events")
