"""Natural-language rule authoring: draft SQL with a Foundation Model, backtest against adjudicated outcomes, promote."""

import json
import os
import re
import time

from databricks.sdk.errors import DatabricksError

from server import queries as Q
from server.config import UC_CATALOG, UC_SCHEMA, get_workspace_client
from server.sql import SqlError, cached, parallel, run_sql

T = Q.T
ENDPOINT = os.environ.get("RULE_AUTHOR_ENDPOINT", "databricks-claude-sonnet-5-5")
SOURCE_TABLES = [
    "gold_claims", "gold_claim_weeks", "gold_applicant_profile", "gold_identity_links", "intel_ndnh_quarterly_wages",
    "intel_ssa_death_master", "intel_bop_inmates", "intel_treasury_dnp", "intel_ssa_identity", "ref_state_programs",
]
REQUIRED = ["applicant_key", "state_code", "claim_id", "evidence", "amount_at_risk"]
FORBIDDEN = re.compile(r"\b(insert|update|delete|merge|drop|create|alter|grant|revoke|truncate|copy|call|optimize|vacuum|refresh|use|set|reset)\b", re.I)
QUALIFIED = re.compile(r"\b([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\b")
SEVERITY_SCORE = {"critical": 0.98, "high": 0.86, "medium": 0.62}
GATES = {"min_precision": 0.6, "max_hit_rate": 0.15}

EXAMPLES = [
    "Flag claimants paid by three or more states for overlapping weeks",
    "Claimants whose payment account is shared by five or more claimants filing in different states",
    "Claims paid at the state maximum weekly benefit where all base-period wages came from a single quarter",
    "Claims that certified zero work search contacts for four or more consecutive paid weeks",
]


class RuleError(ValueError):
    pass


def schema_context() -> str:
    def load():
        names = ", ".join(repr(t) for t in SOURCE_TABLES)
        cols = run_sql(f"""
            SELECT c.table_name, t.comment AS table_comment, c.column_name, lower(c.data_type) AS data_type, c.comment
            FROM {UC_CATALOG}.information_schema.columns c
            JOIN {UC_CATALOG}.information_schema.tables t USING (table_catalog, table_schema, table_name)
            WHERE c.table_schema = '{UC_SCHEMA}' AND c.table_name IN ({names})
            ORDER BY c.table_name, c.ordinal_position
        """, as_service=True)
        out, current = [], None
        for c in cols:
            if c["table_name"] != current:
                current = c["table_name"]
                out.append(f"\n{T}.{current}" + (f"  -- {c['table_comment']}" if c["table_comment"] else ""))
            out.append(f"  {c['column_name']} {c['data_type']}" + (f"  -- {c['comment']}" if c["comment"] else ""))
        return "\n".join(out)
    return cached("rule_schema", 900, load)


def system_prompt() -> str:
    return f"""You write detection rules for the U.S. Department of Labor unemployment insurance (UI) integrity program, in Databricks SQL.
Return ONLY a JSON object with keys:
  "name": rule title, at most 6 words
  "category": "fraud" or "eligibility"
  "severity": "critical", "high" or "medium"
  "rationale": one sentence a program analyst would understand, naming the signal
  "sql": the query

SQL contract:
- One SELECT statement (CTEs allowed). No ORDER BY, LIMIT, DDL, DML, or semicolons.
- Only these fully qualified tables: {", ".join(f"{T}.{t}" for t in SOURCE_TABLES)}.
- Return exactly these columns, one row per flagged state claim:
  applicant_key STRING, state_code STRING, claim_id STRING,
  evidence STRING (short reason with the specific values, e.g. "Paid by CA, NY, TX for 9 overlapping weeks"),
  amount_at_risk DOUBLE (dollars already paid on that claim that the finding puts at risk).
- Never put names, SSNs, dates of birth, bank tokens, device ids or IP addresses in evidence.
- applicant_key identifies a person across states; gold_claim_weeks has one row per claim week (status 'paid' with paid_amount).
- Use only columns listed below.

Schema (Unity Catalog metadata):
{schema_context()}"""


def _llm(messages: list[dict]) -> str:
    w = get_workspace_client()
    try:
        r = w.api_client.do("POST", f"/serving-endpoints/{ENDPOINT}/invocations", body={"messages": messages, "max_tokens": 1800})
    except DatabricksError as e:
        raise RuleError(f"Rule author model {ENDPOINT} failed: {str(e)[:300]}") from e
    content = r["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuleError("The model did not return a rule definition")
    try:
        d = json.loads(m.group(0))
    except ValueError as e:
        raise RuleError(f"The model returned malformed JSON: {e}") from e
    d["category"] = d.get("category") if d.get("category") in ("fraud", "eligibility") else "fraud"
    d["severity"] = d.get("severity") if d.get("severity") in SEVERITY_SCORE else "high"
    d["sql"] = clean_sql(d.get("sql", ""))
    return d


def clean_sql(sql: str) -> str:
    sql = re.sub(r"^```(sql)?|```$", "", (sql or "").strip(), flags=re.I | re.M).strip().rstrip(";").strip()
    if not re.match(r"^(select|with)\b", sql, re.I):
        raise RuleError("Rule SQL must be a single SELECT query")
    code = re.sub(r"--[^\n]*", "", re.sub(r"'(?:[^'\\]|\\.)*'", "''", sql))
    if ";" in code:
        raise RuleError("Rule SQL must be a single statement")
    if FORBIDDEN.search(code):
        raise RuleError("Rule SQL may only read data")
    for cat, sch, tbl in QUALIFIED.findall(code):
        if f"{cat}.{sch}" != T or tbl not in SOURCE_TABLES:
            raise RuleError(f"Rule SQL may not read {cat}.{sch}.{tbl}")
    return sql + "\n"


def check_contract(sql: str):
    run_sql(f"WITH r AS ({sql}) SELECT {', '.join(REQUIRED[:4])}, CAST(amount_at_risk AS DOUBLE) AS amount_at_risk FROM r LIMIT 0")


def draft(prompt: str) -> dict:
    started = time.time()
    messages = [{"role": "system", "content": system_prompt()}, {"role": "user", "content": prompt}]
    reply = _llm(messages)
    attempts = 1
    try:
        rule = _parse(reply)
        check_contract(rule["sql"])
    except (SqlError, RuleError) as e:
        attempts = 2
        messages += [{"role": "assistant", "content": reply}, {"role": "user", "content": f"That rule was rejected: {str(e)[:600]}\nReturn the corrected JSON."}]
        reply = _llm(messages)
        rule = _parse(reply)
        check_contract(rule["sql"])
    rule.update({"prompt": prompt, "author_model": ENDPOINT, "attempts": attempts, "draft_seconds": round(time.time() - started, 1)})
    return rule


def backtest(sql: str, category: str) -> dict:
    sql = clean_sql(sql)
    started = time.time()
    hits_cte = f"WITH r AS ({sql}), h AS (SELECT applicant_key, sum(amount_at_risk) AS amt FROM r GROUP BY applicant_key)"
    try:
        r = parallel(
            totals=lambda: run_sql(f"WITH r AS ({sql}) SELECT count(*) AS claims, count(DISTINCT applicant_key) AS claimants, sum(amount_at_risk) AS at_risk FROM r"),
            population=lambda: run_sql(f"SELECT count(*) AS n FROM {T}.gold_applicant_profile"),
            outcomes=lambda: run_sql(f"""{hits_cte}
                SELECT count(*) AS n, count_if(a.label_fraud = 1) AS fraud, count_if(a.label_ineligible = 1) AS ineligible,
                  count_if(a.label_fraud = 1 OR a.label_ineligible = 1) AS bad
                FROM h LEFT JOIN {T}.ref_applicants a USING (applicant_key)"""),
            lift=lambda: run_sql(f"""{hits_cte},
                x AS (
                  SELECT h.applicant_key, h.amt, (a.label_fraud = 1 OR a.label_ineligible = 1) AS bad,
                    h.applicant_key IN (SELECT applicant_key FROM {T}.gold_check_findings) AS in_rules,
                    h.applicant_key IN (SELECT applicant_key FROM {T}.gold_ml_scores
                      WHERE ml_score >= (SELECT max(value) FROM {T}.ml_model_metrics WHERE metric = 'threshold')) AS in_ml
                  FROM h LEFT JOIN {T}.ref_applicants a USING (applicant_key)
                )
                SELECT count_if(NOT in_rules) AS beyond_rules, count_if(NOT in_rules AND in_ml) AS ml_only_explained,
                  sum(CASE WHEN NOT in_rules THEN amt ELSE 0 END) AS beyond_rules_at_risk,
                  count_if(NOT in_rules AND NOT in_ml) AS new_claimants, count_if(NOT in_rules AND NOT in_ml AND bad) AS new_bad,
                  sum(CASE WHEN NOT in_rules AND NOT in_ml THEN amt ELSE 0 END) AS new_at_risk
                FROM x"""),
            states=lambda: run_sql(f"WITH r AS ({sql}) SELECT state_code, count(DISTINCT applicant_key) AS claimants, sum(amount_at_risk) AS at_risk FROM r GROUP BY state_code ORDER BY claimants DESC"),
            sample=lambda: run_sql(f"""WITH r AS ({sql})
                SELECT r.applicant_key, concat(p.first_name, ' ', p.last_name) AS name, r.state_code, r.claim_id, r.evidence, r.amount_at_risk
                FROM r JOIN {T}.gold_applicant_profile p USING (applicant_key) ORDER BY r.amount_at_risk DESC LIMIT 8"""),
        )
    except SqlError as e:
        raise RuleError(f"Backtest failed: {str(e)[:400]}") from e
    t, o, lift = r["totals"][0], r["outcomes"][0], r["lift"][0]
    pop = r["population"][0]["n"] or 1
    n = o["n"] or 0
    target = o["fraud"] if category == "fraud" else o["ineligible"]
    precision = (target / n) if n else 0.0
    any_precision = (o["bad"] / n) if n else 0.0
    hit_rate = n / pop
    gates = [
        {"id": "compiles", "label": "Compiles and returns the rule contract columns", "pass": True},
        {"id": "hits", "label": "Flags at least one claim", "pass": (t["claims"] or 0) > 0, "value": t["claims"]},
        {"id": "precision", "label": f"Precision vs adjudicated {category} outcomes ≥ {GATES['min_precision']:.0%}", "pass": precision >= GATES["min_precision"], "value": precision},
        {"id": "breadth", "label": f"Flags ≤ {GATES['max_hit_rate']:.0%} of claimants (not overly broad)", "pass": hit_rate <= GATES["max_hit_rate"], "value": hit_rate},
    ]
    return {
        "claims": t["claims"] or 0, "claimants": t["claimants"] or 0, "at_risk": t["at_risk"] or 0, "population": pop, "hit_rate": hit_rate,
        "precision": precision, "any_precision": any_precision, "outcomes": o,
        "beyond_rules": lift["beyond_rules"] or 0, "ml_only_explained": lift["ml_only_explained"] or 0, "beyond_rules_at_risk": lift["beyond_rules_at_risk"] or 0,
        "new_claimants": lift["new_claimants"] or 0, "new_bad": lift["new_bad"] or 0, "new_at_risk": lift["new_at_risk"] or 0,
        "states": r["states"], "sample": r["sample"], "gates": gates, "passed": all(g["pass"] for g in gates),
        "seconds": round(time.time() - started, 1),
    }


def apply(rule: dict) -> int:
    sql = clean_sql(rule["sql_text"])
    run_sql(f"DELETE FROM {T}.gold_custom_rule_findings WHERE rule_id = :id", {"id": rule["rule_id"]}, as_service=True)
    run_sql(f"""
        INSERT INTO {T}.gold_custom_rule_findings
        SELECT uuid() AS finding_id, r.applicant_key, r.state_code, r.claim_id, :id AS rule_id, :name AS rule_name, :category AS category,
          :severity AS severity, CAST(:score AS DOUBLE) AS score, 'Rule studio' AS intel_source, r.evidence, CAST(r.amount_at_risk AS DOUBLE) AS amount_at_risk,
          'custom' AS finding_source, current_timestamp() AS checked_at
        FROM ({sql}) r
    """, {"id": rule["rule_id"], "name": rule["name"], "category": rule["category"], "severity": rule["severity"],
          "score": SEVERITY_SCORE.get(rule["severity"], 0.86)}, as_service=True)
    rows = run_sql(f"SELECT count(*) AS n FROM {T}.gold_custom_rule_findings WHERE rule_id = :id", {"id": rule["rule_id"]}, as_service=True)
    return rows[0]["n"] if rows else 0


def retire(rule_id: str):
    run_sql(f"DELETE FROM {T}.gold_custom_rule_findings WHERE rule_id = :id", {"id": rule_id}, as_service=True)


def pipeline_snippet(rule: dict) -> str:
    fn = rule["rule_id"].lower().replace("-", "_")
    rationale = (rule.get("rationale") or "").replace('"', "'")
    return (
        f'@rule("{rule["rule_id"]}", "{rule["name"]}", "{rule["category"]}", "{rule["severity"]}", "Rule studio",\n'
        f'      "{rationale}")\n'
        f"def {fn}(c):\n"
        f'    return spark.sql("""\n{rule["sql_text"]}\n""").withColumnRenamed("amount_at_risk", "total_paid")\n'
    )
