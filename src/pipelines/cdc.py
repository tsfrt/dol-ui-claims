from pyspark import pipelines as dp

dp.create_streaming_table(
    name="silver_claim_history",
    comment="SCD Type 2 history of every state claim's status, one row per status interval",
    cluster_by=["applicant_key"],
)

dp.create_auto_cdc_flow(
    target="silver_claim_history",
    source="silver_claim_events",
    keys=["applicant_key", "state_code", "claim_id"],
    sequence_by="event_ts",
    stored_as_scd_type=2,
    except_column_list=["payload", "ssn_norm", "_pipeline_ingested_at"],
)
