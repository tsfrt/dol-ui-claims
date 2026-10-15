from pyspark import pipelines as dp
from pyspark.sql import functions as F

from state_specs import FILE_DROP_STATES, SHARE_STATES, STATE_SPECS, file_columns, share_columns, share_staged_table

catalog = spark.conf.get("catalog", "lanl")
schema = spark.conf.get("schema", "dol_ui")
landing = f"{catalog}.{schema}.bronze_claim_events"
drops = f"/Volumes/{catalog}/{schema}/state_drops"

dp.create_streaming_table(
    name="bronze_claim_events_stream",
    comment="Append-only stream of state UI status events: pushed through Zerobus, pulled from state batch files by Auto Loader, or read from state Delta Shares",
    cluster_by=["state_code"],
)


@dp.append_flow(target="bronze_claim_events_stream", name="zerobus_push")
def zerobus_push():
    return (
        spark.readStream.table(landing)
        .withColumn("ingest_channel", F.lit("zerobus"))
        .withColumn("source_file", F.lit(None).cast("string"))
        .withColumn("_pipeline_ingested_at", F.current_timestamp())
    )


def file_flow(state):
    cols = file_columns(state)

    @dp.append_flow(target="bronze_claim_events_stream", name=f"autoloader_{state.lower()}")
    def flow():
        raw = (
            spark.readStream.format("cloudFiles")
            .option("cloudFiles.format", "csv")
            .option("header", "true")
            .option("cloudFiles.schemaEvolutionMode", "none")
            .option("pathGlobFilter", "*.csv")
            .schema(", ".join(f"{c} STRING" for c in cols))
            .load(f"{drops}/{state.lower()}")
        )
        return raw.select(
            F.col("RECORD_ID").alias("event_id"),
            F.lit(state).alias("state_code"),
            F.lit(STATE_SPECS[state]["agency"]).alias("agency"),
            F.to_timestamp("EVENT_TS").alias("event_ts"),
            F.col("_metadata.file_modification_time").alias("ingested_at"),
            F.to_json(F.struct(*cols[2:])).alias("payload"),
            F.lit("file_drop").alias("ingest_channel"),
            F.col("_metadata.file_name").alias("source_file"),
            F.current_timestamp().alias("_pipeline_ingested_at"),
        )

    return flow


for _state in FILE_DROP_STATES:
    file_flow(_state)


def share_source(state):
    """The mounted share catalog when configured, otherwise the staged stand-in for the state's table."""
    mounted = spark.conf.get(f"share_catalog_{state.lower()}", "")
    if mounted:
        return f"{mounted}.uia.{STATE_SPECS[state]['share']['table']}"
    return share_staged_table(catalog, state)


def share_flow(state):
    spec = STATE_SPECS[state]
    fields = [c for c, _ in share_columns(state)[1:-1]]

    @dp.append_flow(target="bronze_claim_events_stream", name=f"delta_share_{state.lower()}")
    def flow():
        return (
            spark.readStream.option("readChangeFeed", "true").table(share_source(state))
            .where("_change_type = 'insert'")
            .select(
                F.col("event_id"),
                F.lit(state).alias("state_code"),
                F.lit(spec["agency"]).alias("agency"),
                F.col("status_changed_at").alias("event_ts"),
                F.col("_commit_timestamp").alias("ingested_at"),
                F.to_json(F.struct(*fields)).alias("payload"),
                F.lit("delta_share").alias("ingest_channel"),
                F.concat(F.lit(f"{spec['share']['name']}@v"), F.col("_commit_version").cast("string")).alias("source_file"),
                F.current_timestamp().alias("_pipeline_ingested_at"),
            )
        )

    return flow


for _state in SHARE_STATES:
    share_flow(_state)
