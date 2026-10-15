# Databricks notebook source
# MAGIC %md
# MAGIC ## Governance: attribute-based access control over claimant PII and state ownership
# MAGIC
# MAGIC Columns are tagged with governed tags (system `class.*` PII classes, `pii_class`, `pii_field`, `state`, `geo_region_filter`).
# MAGIC Schema-level ABAC policies mask PII and filter rows by state for every table that carries those tags, now and in the future.
# MAGIC Who sees what is decided by `ref_data_entitlements`, so access changes take effect on the next query without regrants.

# COMMAND ----------

dbutils.widgets.text("catalog", "lanl")
dbutils.widgets.text("schema", "dol_ui")
dbutils.widgets.text("app_principal", "")
dbutils.widgets.text("persona_federal_principal", "")
dbutils.widgets.text("persona_ca_principal", "")
dbutils.widgets.text("warehouse_id", "")
dbutils.widgets.text("bundle_files_path", "")

C = dbutils.widgets.get("catalog")
S = dbutils.widgets.get("schema")
T = f"{C}.{S}"
runner = spark.sql("SELECT current_user()").first()[0]
app_sp = dbutils.widgets.get("app_principal")
persona_fed = dbutils.widgets.get("persona_federal_principal")
persona_ca = dbutils.widgets.get("persona_ca_principal")

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {T}.ref_data_entitlements (
  principal STRING NOT NULL COMMENT 'User email or service principal application id, as returned by current_user()',
  display_name STRING,
  role STRING,
  state_scope ARRAY<STRING> COMMENT 'State codes the principal may see; * means all states',
  pii_cleared BOOLEAN COMMENT 'May view unmasked claimant PII'
) COMMENT 'Data entitlements registry enforced by Unity Catalog ABAC policies on {T}'
""")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {T}.gold_custom_rule_findings (
  finding_id STRING, applicant_key STRING, state_code STRING, claim_id STRING, rule_id STRING, rule_name STRING, category STRING,
  severity STRING, score DOUBLE, intel_source STRING, evidence STRING, amount_at_risk DOUBLE, finding_source STRING, checked_at TIMESTAMP
) COMMENT 'Findings from analyst-authored rules promoted in the Rule studio (definitions in Lakebase custom_rules)'
""")

seed = [
    (runner, "Pipeline and job runner", "Platform owner", ["*"], True),
    (app_sp, "Claims Integrity app", "Federal investigator", ["*"], True),
    (persona_fed, "Federal analyst (no PII clearance)", "Federal analyst", ["*"], False),
    (persona_ca, "CA EDD state analyst", "State analyst", ["CA"], False),
]
seed = [r for r in seed if r[0]]
spark.createDataFrame(seed, "principal STRING, display_name STRING, role STRING, state_scope ARRAY<STRING>, pii_cleared BOOLEAN") \
    .createOrReplaceTempView("seed_entitlements")
# Platform identities are always re-asserted; persona rows keep any live edits made from the app.
spark.sql(f"""
MERGE INTO {T}.ref_data_entitlements t USING seed_entitlements s ON t.principal = s.principal
WHEN MATCHED AND s.pii_cleared THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *
""")

# COMMAND ----------

functions = {
    "pii_visible": """() RETURNS BOOLEAN
      COMMENT 'True when the caller is PII-cleared in ref_data_entitlements'
      RETURN EXISTS (SELECT 1 FROM {T}.ref_data_entitlements e WHERE e.principal = current_user() AND e.pii_cleared)""",
    "mask_pii_string": """(v STRING) RETURNS STRING
      COMMENT 'Redacts a PII value to its first character unless the caller is PII-cleared'
      RETURN CASE WHEN v IS NULL OR {T}.pii_visible() THEN v ELSE concat(left(v, 1), repeat('•', 5)) END""",
    "mask_pii_date": """(v DATE) RETURNS DATE
      COMMENT 'Hides dates of birth unless the caller is PII-cleared'
      RETURN CASE WHEN {T}.pii_visible() THEN v END""",
    "mask_pii_text": """(v STRING) RETURNS STRING
      COMMENT 'Scrubs SSNs and name/birth fields from free text and raw state payloads unless the caller is PII-cleared'
      RETURN CASE WHEN v IS NULL OR {T}.pii_visible() THEN v ELSE
        regexp_replace(
          regexp_replace(v, '[0-9]{3}-?[0-9]{2}-?[0-9]{4}', '•••-••-••••'),
          '"([A-Za-z_]*(name|first|last|fname|lname|surname|given|dob|birth)[A-Za-z_]*)"\\\\s*:\\\\s*"[^"]*"', '"$1": "•••••"')
      END""",
    "state_in_scope": """(state STRING) RETURNS BOOLEAN
      COMMENT 'Row filter: caller is entitled to the state agency that owns the row'
      RETURN EXISTS (SELECT 1 FROM {T}.ref_data_entitlements e WHERE e.principal = current_user()
        AND (array_contains(e.state_scope, '*') OR array_contains(e.state_scope, state)))""",
    "states_in_scope": """(states ARRAY<STRING>) RETURNS BOOLEAN
      COMMENT 'Row filter for multi-state rows: caller is entitled to at least one of the states'
      RETURN EXISTS (SELECT 1 FROM {T}.ref_data_entitlements e WHERE e.principal = current_user()
        AND (array_contains(e.state_scope, '*') OR arrays_overlap(e.state_scope, states)))""",
}
for name, body in functions.items():
    spark.sql(f"CREATE OR REPLACE FUNCTION {T}.{name}{body.replace('{T}', T).replace('{RUNNER}', runner)}")

# COMMAND ----------

TAGS = {
    "class.name": ["first_name", "last_name"],
    "class.us_ssn": ["ssn_last4", "ssn_norm"],
    "class.date_of_birth": ["dob"],
    "class.us_bank_number": ["bank_token"],
    "pii_class=device_identifier": ["device_id"],
    "pii_class=network_identifier": ["ip_address", "ip_subnet"],
    "pii_field": ["payload", "summary", "report", "link_value"],
    "state": ["state_code"],
    "geo_region_filter": ["states"],
}
TAGGED_TABLES = [
    "silver_claim_events", "silver_claim_history", "gold_claims", "gold_claim_weeks", "gold_applicant_profile",
    "gold_check_findings", "gold_identity_links", "gold_state_summary", "gold_ml_findings", "gold_agent_findings",
    "gold_custom_rule_findings", "intel_ssa_identity", "ref_applicants",
]
cols = spark.sql(f"""
  SELECT table_name, column_name FROM {C}.information_schema.columns
  WHERE table_schema = '{S}' AND table_name IN ({', '.join(repr(t) for t in TAGGED_TABLES)})
""").collect()
present = {(r.table_name, r.column_name) for r in cols}
tagged = 0
for tag, columns in TAGS.items():
    key, _, value = tag.partition("=")
    assignment = f"`{key}` = `{value}`" if value else f"`{key}`"
    for table in TAGGED_TABLES:
        for col in columns:
            if (table, col) in present:
                spark.sql(f"SET TAG ON COLUMN {T}.{table}.{col} {assignment}")
                tagged += 1
print(f"tagged {tagged} columns")

# COMMAND ----------

POLICIES = {
    "dol_mask_pii_strings": """COMMENT 'Mask claimant names, SSNs, bank accounts, devices and IPs unless PII cleared'
      COLUMN MASK {T}.mask_pii_string TO `account users` EXCEPT `{RUNNER}` FOR TABLES
      MATCH COLUMNS has_tag('class.name') OR has_tag('class.us_ssn') OR has_tag('class.us_bank_number') OR has_tag('pii_class') AS c
      ON COLUMN c""",
    "dol_mask_pii_dates": """COMMENT 'Hide dates of birth unless PII cleared'
      COLUMN MASK {T}.mask_pii_date TO `account users` EXCEPT `{RUNNER}` FOR TABLES
      MATCH COLUMNS has_tag('class.date_of_birth') AS c ON COLUMN c""",
    "dol_mask_pii_text": """COMMENT 'Scrub PII from raw state payloads, investigator narratives and link values unless PII cleared'
      COLUMN MASK {T}.mask_pii_text TO `account users` EXCEPT `{RUNNER}` FOR TABLES
      MATCH COLUMNS has_tag('pii_field') AS c ON COLUMN c""",
    "dol_state_scope": """COMMENT 'State agency analysts only see rows owned by their state'
      ROW FILTER {T}.state_in_scope TO `account users` EXCEPT `{RUNNER}` FOR TABLES
      MATCH COLUMNS has_tag('state') AS s USING COLUMNS (s)""",
    "dol_state_scope_multi": """COMMENT 'Multi-state claimant rows are visible to any state the claimant filed in'
      ROW FILTER {T}.states_in_scope TO `account users` EXCEPT `{RUNNER}` FOR TABLES
      MATCH COLUMNS has_tag('geo_region_filter') AS s USING COLUMNS (s)""",
}
for name in ["dol_mask_names", *POLICIES]:
    try:
        spark.sql(f"DROP POLICY {name} ON SCHEMA {T}")
    except Exception:
        pass
for name, body in POLICIES.items():
    spark.sql(f"CREATE POLICY {name} ON SCHEMA {T} {body.replace('{T}', T).replace('{RUNNER}', runner)}")
print(f"applied {len(POLICIES)} policies on {T}")

# COMMAND ----------

for principal in [persona_fed, persona_ca]:
    if principal:
        spark.sql(f"GRANT USE CATALOG ON CATALOG {C} TO `{principal}`")
        spark.sql(f"GRANT USE SCHEMA, SELECT ON SCHEMA {T} TO `{principal}`")
if app_sp:
    for table in ["ref_data_entitlements", "gold_custom_rule_findings"]:
        spark.sql(f"GRANT SELECT, MODIFY ON TABLE {T}.{table} TO `{app_sp}`")
    if spark.sql(f"SHOW VOLUMES IN {T} LIKE 'state_drops'").count():
        spark.sql(f"GRANT READ VOLUME ON VOLUME {T}.state_drops TO `{app_sp}`")

display(spark.table(f"{T}.ref_data_entitlements"))

# COMMAND ----------

# The analyst app links to the rules, training and agent source in this bundle, so its service principal needs read access.
bundle_files = dbutils.widgets.get("bundle_files_path")
if app_sp and bundle_files:
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.iam import AccessControlRequest, PermissionLevel

    w = WorkspaceClient()
    folder = w.workspace.get_status(bundle_files)
    w.permissions.update("directories", str(folder.object_id), access_control_list=[
        AccessControlRequest(service_principal_name=app_sp, permission_level=PermissionLevel.CAN_READ),
    ])
    print(f"granted CAN_READ on {bundle_files} to the app service principal")
