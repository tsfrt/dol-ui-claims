from pyspark import pipelines as dp
from pyspark.sql import functions as F

from state_parsers import parse_columns


@dp.table(
    name="silver_claim_events",
    comment="Canonical UI claim status events normalized from 14 state contracts: 10 streamed through Zerobus, Michigan pulled from batch files, Ohio, Colorado and North Carolina read from Delta Shares. Full SSN is replaced with a SHA-256 hash and last four digits.",
    cluster_by=["state_code", "applicant_key"],
)
@dp.expect_or_drop("known_status_code", "canonical_status IS NOT NULL")
@dp.expect_or_drop("valid_ssn", "length(ssn_norm) = 9")
@dp.expect("has_claim_week", "week_start IS NOT NULL")
@dp.expect("has_benefit_amount", "canonical_status <> 'paid' OR paid_amount > 0")
def silver_claim_events():
    df = spark.readStream.table("bronze_claim_events_stream")
    for name, expr in parse_columns(F.col("state_code"), F.col("payload")).items():
        df = df.withColumn(name, expr)
    return (
        df.withColumn("ssn_hash", F.sha2(F.col("ssn_norm"), 256))
        .withColumn("applicant_key", F.col("ssn_hash"))
        .withColumn("ssn_last4", F.substring("ssn_norm", 6, 4))
        .select(
            "event_id", "state_code", "agency", "event_ts", "ingested_at", "applicant_key", "ssn_hash", "ssn_norm", "ssn_last4",
            "first_name", "last_name", "dob", "claim_id", "week_start", "raw_status", "canonical_status",
            "weekly_benefit_amount", "paid_amount", "employer_name", "county", "separation_reason", "work_search_contacts",
            "bank_token", "device_id", "ip_address", "payload", "ingest_channel", "source_file", "_pipeline_ingested_at",
        )
    )
