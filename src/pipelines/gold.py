from pyspark import pipelines as dp
from pyspark.sql import functions as F

catalog = spark.conf.get("catalog", "lanl")
schema = spark.conf.get("schema", "dol_ui")
ns = f"{catalog}.{schema}"


@dp.materialized_view(
    name="gold_claims",
    comment="One row per state claim: current status, payments, filing attributes, and work search compliance",
    cluster_by=["applicant_key"],
)
def gold_claims():
    ev = spark.read.table("silver_claim_events")
    paid = F.col("canonical_status") == "paid"
    claims = ev.groupBy("applicant_key", "state_code", "claim_id").agg(
        F.first("ssn_hash").alias("ssn_hash"),
        F.first("ssn_last4").alias("ssn_last4"),
        F.min_by("first_name", "event_ts").alias("first_name"),
        F.min_by("last_name", "event_ts").alias("last_name"),
        F.min_by("dob", "event_ts").alias("dob"),
        F.first("agency").alias("agency"),
        F.min("event_ts").alias("filed_at"),
        F.max("event_ts").alias("last_event_ts"),
        F.max_by("canonical_status", "event_ts").alias("current_status"),
        F.max_by("raw_status", "event_ts").alias("current_raw_status"),
        F.min("week_start").alias("first_week"),
        F.max(F.when(paid, F.col("week_start"))).alias("last_paid_week"),
        F.count(F.when(paid, 1)).alias("weeks_paid"),
        F.coalesce(F.sum(F.when(paid, F.col("paid_amount"))), F.lit(0.0)).alias("total_paid"),
        F.max("weekly_benefit_amount").alias("weekly_benefit_amount"),
        F.max("employer_name").alias("employer_name"),
        F.max("county").alias("county"),
        F.max("separation_reason").alias("separation_reason"),
        F.max("bank_token").alias("bank_token"),
        F.max("device_id").alias("device_id"),
        F.max("ip_address").alias("ip_address"),
        F.count(F.when(paid & (F.col("work_search_contacts") == 0), 1)).alias("zero_work_search_weeks"),
        F.max(F.when(F.col("canonical_status") == "exhausted", 1).otherwise(0)).cast("boolean").alias("exhausted"),
        F.count("*").alias("event_count"),
    )
    return claims.withColumn("ip_subnet", F.substring_index("ip_address", ".", 3))


@dp.materialized_view(
    name="gold_claim_weeks",
    comment="Week-by-week claim status and payment for timeline views",
    cluster_by=["applicant_key"],
)
def gold_claim_weeks():
    ev = spark.read.table("silver_claim_events")
    return ev.groupBy("applicant_key", "state_code", "claim_id", "week_start").agg(
        F.max_by("canonical_status", "event_ts").alias("status"),
        F.max_by("raw_status", "event_ts").alias("raw_status"),
        F.coalesce(F.sum("paid_amount"), F.lit(0.0)).alias("paid_amount"),
        F.max("work_search_contacts").alias("work_search_contacts"),
        F.max("event_ts").alias("event_ts"),
    )


@dp.materialized_view(
    name="gold_applicant_profile",
    comment="Cross-state claimant profile resolved on SSN hash, with lifetime claims and payments",
    cluster_by=["applicant_key"],
)
def gold_applicant_profile():
    c = spark.read.table("gold_claims")
    return c.groupBy("applicant_key").agg(
        F.first("ssn_hash").alias("ssn_hash"),
        F.first("ssn_last4").alias("ssn_last4"),
        F.max_by("first_name", "filed_at").alias("first_name"),
        F.max_by("last_name", "filed_at").alias("last_name"),
        F.max_by("dob", "filed_at").alias("dob"),
        F.min_by("state_code", "filed_at").alias("home_state"),
        F.array_sort(F.collect_set("state_code")).alias("states"),
        F.countDistinct("state_code").alias("state_count"),
        F.count("*").alias("claim_count"),
        F.sum("weeks_paid").alias("weeks_paid"),
        F.round(F.sum("total_paid"), 2).alias("total_paid"),
        F.max_by("current_status", "last_event_ts").alias("latest_status"),
        F.max_by("state_code", "last_event_ts").alias("latest_state"),
        F.min("filed_at").alias("first_filed_at"),
        F.max("last_event_ts").alias("last_event_ts"),
    )


@dp.materialized_view(
    name="gold_identity_links",
    comment="Bank tokens, devices, and IP subnets shared by more than one claimant (fraud ring signals)",
)
def gold_identity_links():
    c = spark.read.table("gold_claims")
    links = (
        c.select("applicant_key", "state_code", "total_paid", F.lit("bank_account").alias("link_type"), F.col("bank_token").alias("link_value"))
        .unionByName(c.select("applicant_key", "state_code", "total_paid", F.lit("device").alias("link_type"), F.col("device_id").alias("link_value")))
        .unionByName(c.select("applicant_key", "state_code", "total_paid", F.lit("ip_subnet").alias("link_type"), F.col("ip_subnet").alias("link_value")))
        .filter(F.col("link_value").isNotNull())
    )
    return (
        links.groupBy("link_type", "link_value")
        .agg(
            F.countDistinct("applicant_key").alias("applicant_count"),
            F.array_sort(F.collect_set("applicant_key")).alias("applicant_keys"),
            F.array_sort(F.collect_set("state_code")).alias("states"),
            F.round(F.sum("total_paid"), 2).alias("total_paid"),
        )
        .filter(F.col("applicant_count") > 1)
    )


@dp.materialized_view(
    name="gold_interstate_pairs",
    comment="Claimants paid by two states for overlapping weeks, aggregated by state pair",
)
def gold_interstate_pairs():
    c = spark.read.table("gold_claims").filter(F.col("weeks_paid") > 0)
    a, b = c.alias("a"), c.alias("b")
    overlap = a.join(
        b,
        (F.col("a.applicant_key") == F.col("b.applicant_key"))
        & (F.col("a.state_code") < F.col("b.state_code"))
        & (F.col("a.first_week") <= F.col("b.last_paid_week"))
        & (F.col("b.first_week") <= F.col("a.last_paid_week")),
    )
    return overlap.groupBy(F.col("a.state_code").alias("state_a"), F.col("b.state_code").alias("state_b")).agg(
        F.countDistinct("a.applicant_key").alias("claimants"),
        F.round(F.sum(F.least("a.total_paid", "b.total_paid")), 2).alias("duplicate_paid"),
    )


@dp.materialized_view(
    name="gold_state_summary",
    comment="Per-state operations summary with the raw status vocabulary each agency sends",
)
def gold_state_summary():
    c = spark.read.table("gold_claims")
    ev = spark.read.table("silver_claim_events")
    programs = spark.read.table(f"{ns}.ref_state_programs")
    claims = c.groupBy("state_code").agg(
        F.countDistinct("applicant_key").alias("claimants"),
        F.count("*").alias("claims"),
        F.count(F.when(F.col("current_status").isin("paid", "pending", "filed", "appealed"), 1)).alias("active_claims"),
        F.count(F.when(F.col("current_status") == "denied", 1)).alias("denied_claims"),
        F.sum("weeks_paid").alias("weeks_paid"),
        F.round(F.sum("total_paid"), 2).alias("total_paid"),
        F.round(F.avg("weekly_benefit_amount"), 2).alias("avg_wba"),
    )
    events = ev.groupBy("state_code").agg(
        F.count("*").alias("events"),
        F.max("ingested_at").alias("last_ingested_at"),
        F.array_sort(F.collect_set("raw_status")).alias("raw_status_codes"),
    )
    return programs.join(claims, "state_code", "left").join(events, "state_code", "left")
