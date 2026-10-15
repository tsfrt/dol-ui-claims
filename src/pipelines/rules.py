"""Deterministic fraud and eligibility rules, written as Python and run in the pipeline.

Each rule takes the gold claim set plus federal intel and returns the claims
it flags, along with human-readable evidence and dollars at risk.
"""

from pyspark import pipelines as dp
from pyspark.sql import functions as F

catalog = spark.conf.get("catalog", "lanl")
schema = spark.conf.get("schema", "dol_ui")
ns = f"{catalog}.{schema}"

SEVERITY_SCORE = {"critical": 0.98, "high": 0.86, "medium": 0.62}

RULES = []


def rule(rule_id, name, category, severity, intel_source, description):
    def register(fn):
        RULES.append({"rule_id": rule_id, "rule_name": name, "category": category, "severity": severity, "intel_source": intel_source, "description": description, "fn": fn})
        return fn
    return register


def money(col):
    return F.format_number(col, 0)


@rule("FR-01", "Deceased claimant", "fraud", "critical", "SSA Death Master File",
      "Claim filed using the SSN of a person SSA reports as deceased before the filing date.")
def deceased(c):
    dmf = spark.read.table(f"{ns}.intel_ssa_death_master")
    return c.join(dmf, "ssn_hash").filter(F.to_date("filed_at") > F.col("date_of_death")).select(
        "applicant_key", "state_code", "claim_id", "total_paid",
        F.concat(F.lit("SSA DMF date of death "), F.col("date_of_death").cast("string"), F.lit("; claim filed "),
                 F.datediff(F.to_date("filed_at"), "date_of_death").cast("string"), F.lit(" days later and paid $"), money(F.col("total_paid"))).alias("evidence"),
    )


@rule("FR-02", "Incarcerated while certifying", "fraud", "critical", "Bureau of Prisons SENTRY",
      "Weekly certifications fall inside a federal incarceration period; claimant was not able and available.")
def incarcerated(c):
    bop = spark.read.table(f"{ns}.intel_bop_inmates")
    hit = c.join(bop, "ssn_hash").filter(
        (F.col("weeks_paid") > 0)
        & (F.col("admit_date") <= F.col("last_paid_week"))
        & (F.col("release_date").isNull() | (F.col("release_date") >= F.col("first_week")))
    )
    return hit.select(
        "applicant_key", "state_code", "claim_id", "total_paid",
        F.concat(F.lit("In custody at "), F.col("facility"), F.lit(" since "), F.col("admit_date").cast("string"),
                 F.lit(" while certifying "), F.col("weeks_paid").cast("string"), F.lit(" paid weeks")).alias("evidence"),
    )


@rule("FR-03", "Working while claiming", "fraud", "high", "HHS National Directory of New Hires",
      "New-hire quarterly wages reported by a different employer during weeks the claimant certified as unemployed.")
def working(c):
    ndnh = spark.read.table(f"{ns}.intel_ndnh_quarterly_wages").withColumnRenamed("employer_name", "ndnh_employer")
    q_end = F.date_sub(F.add_months("quarter_start", 3), 1)
    hit = c.join(ndnh, "ssn_hash").filter(
        (F.col("weeks_paid") > 0)
        & (q_end >= F.col("first_week"))
        & (F.col("quarter_start") <= F.col("last_paid_week"))
        & (F.col("employer_name") != F.col("ndnh_employer"))
    )
    agg = hit.groupBy("applicant_key", "state_code", "claim_id", "total_paid", "weeks_paid").agg(
        F.sum("wages").alias("wages"), F.first("ndnh_employer").alias("ndnh_employer"), F.array_join(F.array_sort(F.collect_set("quarter")), ", ").alias("quarters"))
    return agg.select(
        "applicant_key", "state_code", "claim_id", "total_paid",
        F.concat(F.lit("NDNH shows $"), money(F.col("wages")), F.lit(" wages from "), F.col("ndnh_employer"), F.lit(" in "), F.col("quarters"),
                 F.lit(" while certifying "), F.col("weeks_paid").cast("string"), F.lit(" weeks unemployed")).alias("evidence"),
    )


@rule("FR-04", "Concurrent interstate claims", "fraud", "high", "Interstate Connection Network (ICON)",
      "Same SSN paid by two states for overlapping benefit weeks.")
def interstate(c):
    p = c.filter(F.col("weeks_paid") > 0)
    a, b = p.alias("a"), p.alias("b")
    hit = a.join(b, (F.col("a.applicant_key") == F.col("b.applicant_key")) & (F.col("a.state_code") != F.col("b.state_code"))
                 & (F.col("a.first_week") <= F.col("b.last_paid_week")) & (F.col("b.first_week") <= F.col("a.last_paid_week")))
    return hit.select(
        F.col("a.applicant_key").alias("applicant_key"), F.col("a.state_code").alias("state_code"), F.col("a.claim_id").alias("claim_id"),
        F.col("a.total_paid").alias("total_paid"),
        F.concat(F.lit("Overlapping paid weeks with "), F.col("b.state_code"), F.lit(" claim "), F.col("b.claim_id"),
                 F.lit(" ($"), money(F.col("b.total_paid")), F.lit(" paid there)")).alias("evidence"),
    )


@rule("FR-05", "SSA identity mismatch", "fraud", "high", "SSA Identity Verification (SSOLV)",
      "Name or date of birth on the claim does not match SSA records for the SSN, indicating a stolen identity.")
def identity(c):
    ssa = spark.read.table(f"{ns}.intel_ssa_identity").select("ssn_hash", F.col("first_name").alias("ssa_first"), F.col("last_name").alias("ssa_last"), F.col("dob").alias("ssa_dob"))
    hit = c.join(ssa, "ssn_hash").filter((F.lower("last_name") != F.lower("ssa_last")) | (F.col("dob") != F.col("ssa_dob")))
    return hit.select(
        "applicant_key", "state_code", "claim_id", "total_paid",
        F.concat(F.lit("Claim: "), F.col("first_name"), F.lit(" "), F.col("last_name"), F.lit(" ("), F.col("dob").cast("string"),
                 F.lit(") vs SSA: "), F.col("ssa_first"), F.lit(" "), F.col("ssa_last"), F.lit(" ("), F.col("ssa_dob").cast("string"), F.lit(")")).alias("evidence"),
    )


@rule("FR-06", "Treasury Do Not Pay match", "fraud", "high", "Treasury Do Not Pay",
      "Claimant appears on a Do Not Pay working-system list that bars federal or federally funded payments.")
def do_not_pay(c):
    dnp = spark.read.table(f"{ns}.intel_treasury_dnp")
    return c.join(dnp, "ssn_hash").select(
        "applicant_key", "state_code", "claim_id", "total_paid",
        F.concat(F.col("list_name"), F.lit(": "), F.col("reason"), F.lit(" (listed "), F.col("listed_date").cast("string"), F.lit(")")).alias("evidence"),
    )


@rule("EL-01", "Monetarily ineligible", "eligibility", "high", "NDNH base-period wages",
      "Base-period wages fall below the state's minimum for monetary eligibility, yet benefits were paid.")
def monetary(c):
    ndnh = spark.read.table(f"{ns}.intel_ndnh_quarterly_wages")
    programs = spark.read.table(f"{ns}.ref_state_programs").select("state_code", "min_base_wages")
    base = c.join(ndnh, "ssn_hash", "left").filter(
        F.col("quarter_start").isNull() | ((F.col("quarter_start") < F.col("first_week")) & (F.col("quarter_start") >= F.add_months("first_week", -18)))
    ).groupBy("applicant_key", "state_code", "claim_id", "total_paid").agg(F.coalesce(F.sum("wages"), F.lit(0.0)).alias("base_wages"))
    return base.join(programs, "state_code").filter((F.col("base_wages") < F.col("min_base_wages")) & (F.col("total_paid") > 0)).select(
        "applicant_key", "state_code", "claim_id", "total_paid",
        F.concat(F.lit("Base-period wages $"), money(F.col("base_wages")), F.lit(" below "), F.col("state_code"), F.lit(" minimum $"), money(F.col("min_base_wages"))).alias("evidence"),
    )


@rule("EL-02", "Disqualifying separation", "eligibility", "high", "State separation determination",
      "Claimant quit voluntarily or was discharged for misconduct but received benefits.")
def separation(c):
    return c.filter(F.col("separation_reason").isin("voluntary_quit", "misconduct") & (F.col("weeks_paid") > 0)).select(
        "applicant_key", "state_code", "claim_id", "total_paid",
        F.concat(F.lit("Separation coded "), F.regexp_replace("separation_reason", "_", " "), F.lit(" by "), F.col("employer_name"),
                 F.lit("; "), F.col("weeks_paid").cast("string"), F.lit(" weeks paid")).alias("evidence"),
    )


@rule("EL-03", "Work search noncompliance", "eligibility", "medium", "Weekly certification",
      "Three or more paid weeks certified with zero work search contacts.")
def work_search(c):
    return c.filter(F.col("zero_work_search_weeks") >= 3).select(
        "applicant_key", "state_code", "claim_id", "total_paid",
        F.concat(F.col("zero_work_search_weeks").cast("string"), F.lit(" paid weeks with no work search contacts (3 required)")).alias("evidence"),
    )


@rule("EL-04", "Paid beyond entitlement", "eligibility", "high", "State benefit year ledger",
      "Weeks paid exceed the state's maximum duration after the claim exhausted.")
def beyond_entitlement(c):
    programs = spark.read.table(f"{ns}.ref_state_programs").select("state_code", "max_weeks")
    hit = c.join(programs, "state_code").filter(F.col("weeks_paid") > F.col("max_weeks"))
    return hit.select(
        "applicant_key", "state_code", "claim_id",
        ((F.col("weeks_paid") - F.col("max_weeks")) * F.col("weekly_benefit_amount")).alias("total_paid"),
        F.concat(F.col("weeks_paid").cast("string"), F.lit(" weeks paid against a "), F.col("max_weeks").cast("string"),
                 F.lit("-week maximum; "), (F.col("weeks_paid") - F.col("max_weeks")).cast("string"), F.lit(" weeks paid after exhaustion")).alias("evidence"),
    )


@dp.materialized_view(
    name="gold_rule_catalog",
    comment="Catalog of Python fraud and eligibility rules applied in the pipeline",
)
def gold_rule_catalog():
    rows = [{**{k: v for k, v in r.items() if k != "fn"}, "base_score": SEVERITY_SCORE[r["severity"]]} for r in RULES]
    return spark.createDataFrame(rows)


@dp.materialized_view(
    name="gold_check_findings",
    comment="Rules-based fraud and eligibility findings with evidence and dollars at risk",
    cluster_by=["applicant_key"],
)
def gold_check_findings():
    claims = spark.read.table("gold_claims")
    out = None
    for r in RULES:
        df = r["fn"](claims).select(
            "applicant_key", "state_code", "claim_id",
            F.lit(r["rule_id"]).alias("rule_id"), F.lit(r["rule_name"]).alias("rule_name"), F.lit(r["category"]).alias("category"),
            F.lit(r["severity"]).alias("severity"), F.lit(SEVERITY_SCORE[r["severity"]]).alias("score"), F.lit(r["intel_source"]).alias("intel_source"),
            "evidence", F.round(F.col("total_paid"), 2).alias("amount_at_risk"),
        )
        out = df if out is None else out.unionByName(df)
    return (
        out.dropDuplicates(["applicant_key", "state_code", "claim_id", "rule_id"])
        .withColumn("finding_source", F.lit("rules"))
        .withColumn("finding_id", F.sha2(F.concat_ws("|", "rule_id", "applicant_key", "state_code", "claim_id"), 256).substr(1, 16))
        .withColumn("checked_at", F.current_timestamp())
    )
