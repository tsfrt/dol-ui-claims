"""Re-applies every active Rule studio rule (definitions in Lakebase) to the current gold tables."""

import argparse
import re

import psycopg
from databricks.sdk import WorkspaceClient
from pyspark.sql import SparkSession

SEVERITY_SCORE = {"critical": 0.98, "high": 0.86, "medium": 0.62}

parser = argparse.ArgumentParser()
parser.add_argument("--catalog", default="lanl")
parser.add_argument("--schema", default="dol_ui")
parser.add_argument("--lakebase_endpoint", default="projects/dol-ui/branches/production/endpoints/primary")
parser.add_argument("--database", default="databricks_postgres")
args, _ = parser.parse_known_args()
T = f"{args.catalog}.{args.schema}"

spark = SparkSession.builder.getOrCreate()
w = WorkspaceClient()
endpoint = w.postgres.get_endpoint(name=args.lakebase_endpoint)
token = w.postgres.generate_database_credential(endpoint=args.lakebase_endpoint).token
user = w.current_user.me()
login = user.user_name if "@" in (user.user_name or "") else user.application_id or user.user_name

with psycopg.connect(host=endpoint.status.hosts.host, dbname=args.database, user=login, password=token, sslmode="require") as conn:
    rules = conn.execute(
        "SELECT rule_id, name, category, severity, sql_text FROM custom_rules WHERE status = 'active' ORDER BY rule_id"
    ).fetchall()

spark.sql(f"DELETE FROM {T}.gold_custom_rule_findings WHERE rule_id NOT IN ({', '.join(repr(r[0]) for r in rules) or 'NULL'})")
for rule_id, name, category, severity, sql_text in rules:
    sql = sql_text.strip().rstrip(";") + "\n"
    if not re.match(r"^(select|with)\b", sql, re.I):
        print(f"skip {rule_id}: not a query")
        continue
    spark.sql(f"DELETE FROM {T}.gold_custom_rule_findings WHERE rule_id = '{rule_id}'")
    spark.sql(f"""
        INSERT INTO {T}.gold_custom_rule_findings
        SELECT uuid(), r.applicant_key, r.state_code, r.claim_id, :id, :name, :category, :severity, CAST(:score AS DOUBLE), 'Rule studio',
          r.evidence, CAST(r.amount_at_risk AS DOUBLE), 'custom', current_timestamp()
        FROM ({sql}) r
    """, args={"id": rule_id, "name": name, "category": category, "severity": severity, "score": SEVERITY_SCORE.get(severity, 0.86)})
    n = spark.sql(f"SELECT count(*) FROM {T}.gold_custom_rule_findings WHERE rule_id = '{rule_id}'").first()[0]
    print(f"{rule_id} {name}: {n} findings")
print(f"applied {len(rules)} active custom rules")
