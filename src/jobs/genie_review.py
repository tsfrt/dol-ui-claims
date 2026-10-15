# Databricks notebook source
# MAGIC %md
# MAGIC ## Genie Agent mode case review
# MAGIC Sends the highest-impact and most ambiguous cases to the Genie agent in Agent mode. The agent
# MAGIC plans its own investigation, runs SQL across claims, intel, and identity links, and returns a verdict.

# COMMAND ----------

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.getcwd(), "..", "genie")))

from agent import build_prompt, run_agent
from databricks.sdk import WorkspaceClient

dbutils.widgets.text("catalog", "lanl")
dbutils.widgets.text("schema", "dol_ui")
dbutils.widgets.text("genie_space_id", "")
dbutils.widgets.text("max_cases", "8")
catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
space_id = dbutils.widgets.get("genie_space_id")
max_cases = int(dbutils.widgets.get("max_cases"))
ns = f"{catalog}.{schema}"

if not space_id:
    dbutils.notebook.exit("No genie_space_id configured; skipping agent review")

# COMMAND ----------

cases = spark.sql(f"""
WITH rules AS (
  SELECT applicant_key, count(*) AS hits, max(category) AS category, sum(amount_at_risk) AS at_risk
  FROM {ns}.gold_check_findings GROUP BY applicant_key
),
c AS (
  SELECT p.applicant_key, concat(p.first_name, ' ', p.last_name) AS name, p.states, p.total_paid,
    coalesce(r.hits, 0) AS rule_hits, r.category, coalesce(m.ml_score, 0) AS ml_score,
    CASE
      WHEN r.hits IS NULL AND m.ml_score >= 0.8 THEN 'ml_only'
      WHEN r.hits IS NOT NULL AND m.ml_score >= 0.6 THEN 'both'
      WHEN r.category = 'eligibility' THEN 'eligibility'
      WHEN p.state_count > 1 AND r.hits IS NOT NULL THEN 'interstate'
      WHEN m.ml_score BETWEEN 0.35 AND 0.6 THEN 'ambiguous'
    END AS bucket
  FROM {ns}.gold_applicant_profile p
  LEFT JOIN rules r USING (applicant_key)
  LEFT JOIN {ns}.gold_ml_scores m USING (applicant_key)
),
ranked AS (
  SELECT *, row_number() OVER (PARTITION BY bucket ORDER BY ml_score DESC, total_paid DESC) AS rn FROM c WHERE bucket IS NOT NULL
)
SELECT * FROM ranked
WHERE (bucket = 'ml_only' AND rn <= 3) OR (bucket = 'both' AND rn <= 2) OR (bucket = 'eligibility' AND rn <= 1)
   OR (bucket = 'interstate' AND rn <= 1) OR (bucket = 'ambiguous' AND rn <= 1)
ORDER BY bucket, rn
LIMIT {max_cases}
""").collect()
print(f"Reviewing {len(cases)} cases with Genie agent {space_id}")

w = WorkspaceClient()
host = w.config.host


def review(row):
    started = datetime.now(timezone.utc)
    try:
        res = run_agent(host, w.config.authenticate(), space_id, build_prompt(row.applicant_key, row.name, list(row.states)))
        status, error = "completed", None
    except Exception as e:
        res, status, error = {"verdict": "NEEDS_REVIEW", "confidence": "LOW", "summary": str(e)[:240], "report": "", "steps": [], "sql_count": 0, "conversation_id": None}, "failed", str(e)[:500]
    return {
        "applicant_key": row.applicant_key, "review_bucket": row.bucket, "status": status, "error": error,
        "verdict": res["verdict"], "confidence": res["confidence"], "summary": res["summary"], "report": res["report"],
        "steps_json": json.dumps(res["steps"]), "sql_count": res["sql_count"], "conversation_id": res["conversation_id"],
        "agent_id": space_id, "started_at": started, "completed_at": datetime.now(timezone.utc),
    }


with ThreadPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(review, cases))

for r in results:
    print(f"{r['applicant_key'][:10]} {r['review_bucket']:<12} {r['status']:<9} {r['verdict']:<13} {r['confidence']:<6} sql={r['sql_count']} {r['summary'][:100]}")

# COMMAND ----------

target = f"{ns}.gold_agent_findings"
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {target} (
  applicant_key STRING, review_bucket STRING, status STRING, error STRING, verdict STRING, confidence STRING,
  summary STRING, report STRING, steps_json STRING, sql_count INT, conversation_id STRING, agent_id STRING,
  started_at TIMESTAMP, completed_at TIMESTAMP
) COMMENT 'Genie Agent mode investigation verdicts per claimant'
""")
if results:
    df = spark.createDataFrame(results, schema=spark.table(target).schema)
    df.createOrReplaceTempView("new_reviews")
    spark.sql(f"MERGE INTO {target} t USING new_reviews s ON t.applicant_key = s.applicant_key WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *")
ok = sum(1 for r in results if r["status"] == "completed")
print(f"{ok}/{len(results)} agent reviews completed")
