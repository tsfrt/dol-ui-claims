"""SQL for the analyst app. Every view of risk derives from the same claim-level CTE."""

import re

from server.config import UC_CATALOG, UC_SCHEMA

T = f"{UC_CATALOG}.{UC_SCHEMA}"
RULE_ID = re.compile(r"^[A-Z]{2}-\d{2}$")


def flags_cte(disabled_rules: list[str], ml_threshold: float) -> str:
    disabled = [r for r in disabled_rules if RULE_ID.match(r)]
    not_in = f"WHERE rule_id NOT IN ({', '.join(repr(r) for r in disabled)})" if disabled else ""
    thr = float(ml_threshold)
    return f"""
rf AS (
  SELECT * FROM (
    SELECT applicant_key, state_code, claim_id, rule_id, rule_name, category, score, amount_at_risk FROM {T}.gold_check_findings
    UNION ALL
    SELECT applicant_key, state_code, claim_id, rule_id, rule_name, category, score, amount_at_risk FROM {T}.gold_custom_rule_findings
  ) u {not_in}
),
ml AS (SELECT applicant_key, ml_score, ml_score >= {thr} AS ml_flag FROM {T}.gold_ml_scores),
ag AS (SELECT applicant_key, verdict FROM {T}.gold_agent_findings WHERE status = 'completed'),
ar AS (
  SELECT p.applicant_key, p.first_name, p.last_name, p.ssn_last4, p.dob, p.states, p.home_state, p.state_count, p.claim_count,
    p.weeks_paid, p.total_paid, p.latest_status, p.last_event_ts,
    coalesce(r.hits, 0) AS rule_hits, coalesce(r.names, array()) AS rule_names, coalesce(r.cats, array()) AS rule_cats,
    coalesce(r.rmax, 0D) AS rmax, coalesce(m.ml_score, 0D) AS ml_score, coalesce(m.ml_flag, false) AS ml_flag, a.verdict AS agent_verdict
  FROM {T}.gold_applicant_profile p
  LEFT JOIN (
    SELECT applicant_key, count(DISTINCT rule_id) AS hits, array_sort(collect_set(rule_name)) AS names,
      array_sort(collect_set(category)) AS cats, max(score) AS rmax
    FROM rf GROUP BY applicant_key
  ) r USING (applicant_key)
  LEFT JOIN ml m USING (applicant_key)
  LEFT JOIN ag a USING (applicant_key)
),
cr AS (
  SELECT c.applicant_key, c.state_code, c.claim_id, c.total_paid,
    greatest(coalesce(x.amt, 0D), CASE WHEN ar.ml_flag OR coalesce(ar.agent_verdict IN ('FRAUD', 'INELIGIBLE'), false) THEN c.total_paid ELSE 0D END) AS at_risk
  FROM {T}.gold_claims c
  JOIN ar USING (applicant_key)
  LEFT JOIN (SELECT applicant_key, state_code, claim_id, max(amount_at_risk) AS amt FROM rf GROUP BY ALL) x USING (applicant_key, state_code, claim_id)
),
flags AS (
  SELECT ar.*, coalesce(cs.at_risk, 0D) AS at_risk,
    (rule_hits > 0 OR ml_flag OR coalesce(agent_verdict IN ('FRAUD', 'INELIGIBLE'), false)) AS flagged,
    (array_contains(rule_cats, 'fraud') OR ml_flag OR coalesce(agent_verdict = 'FRAUD', false)) AS is_fraud,
    (array_contains(rule_cats, 'eligibility') OR coalesce(agent_verdict = 'INELIGIBLE', false)) AS is_inelig,
    1 - (1 - rmax) * (1 - ml_score * 0.95) * (1 - CASE agent_verdict WHEN 'FRAUD' THEN 0.9 WHEN 'INELIGIBLE' THEN 0.75 ELSE 0 END) AS risk_score
  FROM ar LEFT JOIN (SELECT applicant_key, sum(at_risk) AS at_risk FROM cr GROUP BY applicant_key) cs USING (applicant_key)
)"""


def with_flags(disabled, thr, body):
    return f"WITH {flags_cte(disabled, thr)}\n{body}"


KPIS = """
SELECT count(*) AS claimants, sum(total_paid) AS total_paid, sum(weeks_paid) AS weeks_paid,
  count_if(state_count > 1) AS multi_state, count_if(flagged) AS flagged, count_if(is_fraud) AS fraud,
  count_if(is_inelig) AS ineligible, sum(at_risk) AS at_risk,
  (SELECT count(*) FROM {T}.silver_claim_events) AS events,
  (SELECT count_if(ingest_channel = 'file_drop') FROM {T}.silver_claim_events) AS file_events,
  (SELECT count_if(ingest_channel = 'delta_share') FROM {T}.silver_claim_events) AS share_events,
  (SELECT count(DISTINCT state_code) FILTER (WHERE ingest_channel = 'delta_share') FROM {T}.silver_claim_events) AS share_states,
  (SELECT count(DISTINCT source_file) FILTER (WHERE ingest_channel = 'file_drop') FROM {T}.silver_claim_events) AS files,
  (SELECT count(*) FROM {T}.gold_claims) AS claims,
  (SELECT count(DISTINCT state_code) FROM {T}.gold_claims) AS states
FROM flags
""".replace("{T}", T)

STATES = f"""
, sf AS (
  SELECT cr.state_code, count(DISTINCT CASE WHEN f.flagged THEN cr.applicant_key END) AS flagged,
    count(DISTINCT CASE WHEN f.is_fraud THEN cr.applicant_key END) AS fraud,
    count(DISTINCT CASE WHEN f.is_inelig THEN cr.applicant_key END) AS ineligible,
    sum(cr.at_risk) AS at_risk
  FROM cr JOIN flags f USING (applicant_key) GROUP BY cr.state_code
),
tf AS (
  SELECT state_code, max_by(rule_name, n) AS top_finding FROM (
    SELECT state_code, rule_name, count(DISTINCT applicant_key) AS n FROM rf GROUP BY ALL
  ) GROUP BY state_code
)
SELECT s.state_code, s.state_name, s.agency, s.system, s.claimants, s.claims, s.events, s.total_paid, s.active_claims, s.denied_claims,
  s.avg_wba, s.max_wba, s.max_weeks, s.last_ingested_at, s.raw_status_codes,
  coalesce(sf.flagged, 0) AS flagged, coalesce(sf.fraud, 0) AS fraud, coalesce(sf.ineligible, 0) AS ineligible, coalesce(sf.at_risk, 0) AS at_risk,
  coalesce(sf.flagged, 0) / nullif(s.claimants, 0) AS flag_rate, tf.top_finding
FROM {T}.gold_state_summary s LEFT JOIN sf USING (state_code) LEFT JOIN tf USING (state_code)
ORDER BY s.state_code
"""

TECHNIQUES = f"""
SELECT count_if(rule_hits > 0) AS rules, count_if(ml_flag) AS ml,
  count_if(agent_verdict IN ('FRAUD', 'INELIGIBLE')) AS agent, count_if(agent_verdict IS NOT NULL) AS agent_reviews,
  count_if(rule_hits > 0 AND NOT ml_flag) AS rules_only, count_if(rule_hits > 0 AND ml_flag) AS both,
  count_if(rule_hits = 0 AND ml_flag) AS ml_only, sum(CASE WHEN rule_hits = 0 AND ml_flag THEN total_paid ELSE 0 END) AS ml_only_paid,
  (SELECT max(value) FROM {T}.ml_model_metrics WHERE metric = 'roc_auc') AS ml_auc
FROM flags
"""

FINDINGS = f"""
SELECT rule_id, rule_name, category, 'rules' AS technique, count(DISTINCT applicant_key) AS claimants, sum(amt) AS at_risk
FROM (SELECT rule_id, rule_name, category, applicant_key, claim_id, max(amount_at_risk) AS amt FROM rf GROUP BY ALL) GROUP BY ALL
UNION ALL
SELECT 'ML-01', 'Behavioral fraud pattern', 'fraud', 'ml', count(*), sum(total_paid) FROM flags WHERE ml_flag
ORDER BY claimants DESC
"""

TOP_CASES = """
SELECT applicant_key, concat(first_name, ' ', last_name) AS name, states, rule_hits, ml_flag, ml_score, agent_verdict, risk_score, at_risk,
  coalesce(get(rule_names, 0), CASE WHEN ml_flag THEN 'Behavioral fraud pattern' END) AS top_finding
FROM flags WHERE flagged ORDER BY risk_score * 0.4 + least(at_risk / 20000, 1) * 0.6 DESC LIMIT 8
"""

PAIRS = f"SELECT state_a, state_b, claimants, duplicate_paid FROM {T}.gold_interstate_pairs ORDER BY claimants DESC"

RECENT = f"""
SELECT event_id, state_code, agency, event_ts, ingested_at, raw_status, canonical_status, claim_id, ingest_channel, source_file
FROM {T}.silver_claim_events
QUALIFY row_number() OVER (PARTITION BY state_code, canonical_status ORDER BY ingested_at DESC, event_ts DESC) = 1
ORDER BY ingested_at DESC, event_ts DESC LIMIT 16
"""

CASES = """
SELECT applicant_key, concat(first_name, ' ', last_name) AS name, ssn_last4, home_state, states, claim_count, total_paid, latest_status,
  rule_hits, rule_names, rule_cats, ml_score, ml_flag, agent_verdict, risk_score, at_risk, is_fraud, is_inelig
FROM flags
WHERE flagged
  AND (:state IS NULL OR array_contains(states, :state))
  AND (:category IS NULL OR (:category = 'fraud' AND is_fraud) OR (:category = 'eligibility' AND is_inelig))
  AND (:technique IS NULL OR (:technique = 'rules' AND rule_hits > 0) OR (:technique = 'ml' AND ml_flag)
       OR (:technique = 'agent' AND agent_verdict IS NOT NULL) OR (:technique = 'ml_only' AND ml_flag AND rule_hits = 0))
ORDER BY risk_score DESC, at_risk DESC
LIMIT {limit}
"""

APPLICANT = "SELECT * FROM flags WHERE applicant_key = :k"

CLAIMS = f"""
SELECT state_code, claim_id, agency, filed_at, last_event_ts, current_status, current_raw_status, first_week, last_paid_week, weeks_paid,
  total_paid, weekly_benefit_amount, employer_name, county, separation_reason, zero_work_search_weeks, exhausted, bank_token, device_id, ip_subnet
FROM {T}.gold_claims WHERE applicant_key = :k ORDER BY filed_at
"""

WEEKS = f"SELECT state_code, claim_id, week_start, status, raw_status, paid_amount, work_search_contacts FROM {T}.gold_claim_weeks WHERE applicant_key = :k ORDER BY week_start"

RULE_HITS = f"""
SELECT c.rule_id, c.rule_name, c.category, c.severity, c.intel_source, c.description,
  f.evidence, f.state_code, f.amount_at_risk
FROM {T}.gold_rule_catalog c
LEFT JOIN (
  SELECT rule_id, min_by(evidence, state_code) AS evidence, array_join(array_sort(collect_set(state_code)), ', ') AS state_code, sum(amount_at_risk) AS amount_at_risk
  FROM {T}.gold_check_findings WHERE applicant_key = :k GROUP BY rule_id
) f USING (rule_id)
ORDER BY c.rule_id
"""

CUSTOM_HITS = f"""
SELECT rule_id, first(rule_name) AS rule_name, first(category) AS category, first(severity) AS severity, 'Rule studio' AS intel_source,
  min_by(evidence, state_code) AS evidence, array_join(array_sort(collect_set(state_code)), ', ') AS state_code, sum(amount_at_risk) AS amount_at_risk
FROM {T}.gold_custom_rule_findings WHERE applicant_key = :k GROUP BY rule_id ORDER BY rule_id
"""
CUSTOM_STATS = f"""
SELECT rule_id, count(DISTINCT applicant_key) AS claimants, count(*) AS claims, sum(amount_at_risk) AS at_risk, max(checked_at) AS checked_at
FROM {T}.gold_custom_rule_findings GROUP BY rule_id
"""

ML = f"SELECT * FROM {T}.gold_ml_scores WHERE applicant_key = :k"
AGENT = f"SELECT * FROM {T}.gold_agent_findings WHERE applicant_key = :k"

INTEL = {
    "death": f"SELECT date_of_death, source FROM {T}.intel_ssa_death_master WHERE ssn_hash = :k",
    "inmates": f"SELECT facility, admit_date, release_date, source FROM {T}.intel_bop_inmates WHERE ssn_hash = :k",
    "wages": f"SELECT quarter, quarter_start, employer_name, reporting_state, wages FROM {T}.intel_ndnh_quarterly_wages WHERE ssn_hash = :k ORDER BY quarter_start",
    "identity": f"SELECT first_name, last_name, dob, verification_code FROM {T}.intel_ssa_identity WHERE ssn_hash = :k",
    "dnp": f"SELECT list_name, reason, listed_date FROM {T}.intel_treasury_dnp WHERE ssn_hash = :k",
}

LINKS = f"""
SELECT l.link_type, l.link_value, l.applicant_count, l.states, l.total_paid,
  slice(filter(l.applicant_keys, x -> x != :k), 1, 12) AS member_keys
FROM {T}.gold_identity_links l WHERE array_contains(l.applicant_keys, :k)
ORDER BY CASE l.link_type WHEN 'bank_account' THEN 0 WHEN 'device' THEN 1 ELSE 2 END
"""

MEMBERS = """
SELECT applicant_key, concat(first_name, ' ', last_name) AS name, states, ml_score, flagged
FROM flags WHERE array_contains(from_json(:keys, 'array<string>'), applicant_key)
"""

RULE_STATS = f"""
SELECT c.rule_id, c.rule_name, c.category, c.severity, c.intel_source, c.description,
  coalesce(h.claimants, 0) AS claimants, coalesce(h.at_risk, 0) AS at_risk
FROM {T}.gold_rule_catalog c
LEFT JOIN (
  SELECT rule_id, count(DISTINCT applicant_key) AS claimants, sum(amt) AS at_risk
  FROM (SELECT rule_id, applicant_key, claim_id, max(amount_at_risk) AS amt FROM {T}.gold_check_findings GROUP BY ALL) GROUP BY rule_id
) h USING (rule_id)
ORDER BY c.rule_id
"""

MODEL_METRICS = f"SELECT metric, value, run_id, model_name, model_version, trained_at FROM {T}.ml_model_metrics"
MODEL_ROC = f"SELECT fpr, tpr, threshold FROM {T}.ml_roc_curve ORDER BY fpr, tpr"
MODEL_IMPORTANCE = f"SELECT feature, label, importance FROM {T}.ml_feature_importance ORDER BY importance DESC"
ML_THRESHOLD = f"SELECT value FROM {T}.ml_model_metrics WHERE metric = 'threshold'"

AGENT_REVIEWS = f"""
SELECT a.applicant_key, concat(p.first_name, ' ', p.last_name) AS name, a.review_bucket, a.verdict, a.confidence, a.summary, a.sql_count, a.completed_at
FROM {T}.gold_agent_findings a JOIN {T}.gold_applicant_profile p USING (applicant_key)
WHERE a.status = 'completed' ORDER BY a.completed_at DESC
"""

PLATFORM_STATS = f"""
WITH s AS (
  SELECT count(*) AS events, count_if(ingest_channel = 'zerobus') AS zerobus_events, count_if(ingest_channel = 'file_drop') AS file_events,
    count_if(ingest_channel = 'delta_share') AS share_events, count(DISTINCT CASE WHEN ingest_channel = 'delta_share' THEN source_file END) AS share_versions,
    count(DISTINCT CASE WHEN ingest_channel = 'file_drop' THEN source_file END) AS files_loaded, count(DISTINCT state_code) AS states, max(_pipeline_ingested_at) AS last_processed
  FROM {T}.silver_claim_events
),
fo AS (
  SELECT count(*) AS file_outbox_events, count(DISTINCT date_add(d, 6 - weekday(d))) AS file_batches
  FROM (SELECT to_date(timestamp_micros(event_ts_unix_us)) AS d FROM {T}.ref_state_file_outbox)
)
SELECT s.*, fo.*,
  (SELECT count(*) FROM {T}.bronze_claim_events) AS zerobus_landed,
  (SELECT max(ingested_at) FROM {T}.bronze_claim_events) AS last_zerobus_write,
  (SELECT count(*) FROM {T}.ref_state_outbox) AS zerobus_outbox,
  (SELECT count(*) FROM {T}.ref_state_share_outbox) AS share_outbox,
  (SELECT count(*) FROM {T}.bronze_claim_events_stream) AS bronze_rows,
  (SELECT count(*) FROM {T}.silver_claim_history) AS history_rows,
  (SELECT count(*) FROM {T}.gold_claims) AS claims,
  (SELECT count(*) FROM {T}.gold_applicant_profile) AS claimants,
  (SELECT count(*) FROM {T}.gold_claim_weeks) AS claim_weeks,
  (SELECT count(*) FROM {T}.gold_check_findings) AS rule_findings,
  (SELECT count(DISTINCT rule_id) FROM {T}.gold_check_findings) AS rules_firing,
  (SELECT count(*) FROM {T}.gold_ml_findings) AS ml_findings,
  (SELECT count(*) FROM {T}.gold_agent_findings) AS agent_findings,
  (SELECT count(*) FROM {T}.gold_custom_rule_findings) AS custom_findings,
  (SELECT count(DISTINCT rule_id) FROM {T}.gold_custom_rule_findings) AS custom_rules
FROM s CROSS JOIN fo
"""

PLATFORM_INTEL = f"""
SELECT 'SSA Death Master File' AS name, 'intel_ssa_death_master' AS tbl, count(*) AS n FROM {T}.intel_ssa_death_master
UNION ALL SELECT 'BOP inmate roster', 'intel_bop_inmates', count(*) FROM {T}.intel_bop_inmates
UNION ALL SELECT 'NDNH quarterly wages', 'intel_ndnh_quarterly_wages', count(*) FROM {T}.intel_ndnh_quarterly_wages
UNION ALL SELECT 'SSA identity verification', 'intel_ssa_identity', count(*) FROM {T}.intel_ssa_identity
UNION ALL SELECT 'Treasury Do Not Pay', 'intel_treasury_dnp', count(*) FROM {T}.intel_treasury_dnp
UNION ALL SELECT 'BLS LAUS county rates', 'intel_bls_laus', count(*) FROM {T}.intel_bls_laus
"""

PLATFORM_GOVERNANCE = f"""
SELECT count(*) AS tagged_columns, count(DISTINCT table_name) AS tagged_tables, count(DISTINCT tag_name) AS tags,
  (SELECT count(*) FROM {T}.ref_data_entitlements) AS principals
FROM {UC_CATALOG}.information_schema.column_tags WHERE schema_name = '{UC_SCHEMA}'
"""

PLATFORM_FEDERATION = "SELECT count(*) AS wage_rows, count(DISTINCT employer_fein) AS employers FROM mi_uia_tax.uia_tax.employer_wage_detail"

ENTITLEMENTS = f"SELECT principal, display_name, role, state_scope, pii_cleared FROM {T}.ref_data_entitlements ORDER BY pii_cleared DESC, display_name"
COLUMN_TAGS = f"""
SELECT table_name, column_name, tag_name, tag_value FROM {UC_CATALOG}.information_schema.column_tags
WHERE schema_name = '{UC_SCHEMA}' AND table_name NOT LIKE '\\_\\_%' ORDER BY tag_name, table_name, column_name
"""
ACCESS_PROBE = f"""
SELECT current_user() AS principal,
  (SELECT count(*) FROM {T}.gold_claims) AS claims,
  (SELECT array_sort(collect_set(state_code)) FROM {T}.gold_claims) AS states,
  (SELECT sum(total_paid) FROM {T}.gold_claims) AS total_paid,
  (SELECT concat(first_name, ' ', last_name) FROM {T}.gold_applicant_profile ORDER BY applicant_key LIMIT 1) AS sample_name,
  (SELECT cast(dob AS STRING) FROM {T}.gold_applicant_profile ORDER BY applicant_key LIMIT 1) AS sample_dob,
  (SELECT ssn_last4 FROM {T}.gold_applicant_profile ORDER BY applicant_key LIMIT 1) AS sample_ssn4
"""

STATE_STATUS_MIX = f"SELECT current_status AS status, count(*) AS claims FROM {T}.gold_claims WHERE state_code = :s GROUP BY 1"
STATE_SAMPLE = f"SELECT payload FROM {T}.silver_claim_events WHERE state_code = :s AND canonical_status = 'filed' ORDER BY event_ts DESC LIMIT 1"
STATE_FINDINGS = f"""
SELECT rule_id, rule_name, category, 'rules' AS technique, count(DISTINCT applicant_key) AS claimants, sum(amt) AS at_risk
FROM (SELECT rule_id, rule_name, category, applicant_key, claim_id, max(amount_at_risk) AS amt FROM rf WHERE state_code = :s GROUP BY ALL) GROUP BY ALL
UNION ALL
SELECT 'ML-01', 'Behavioral fraud pattern', 'fraud', 'ml', count(DISTINCT c.applicant_key), sum(c.total_paid)
FROM {T}.gold_claims c JOIN ml USING (applicant_key) WHERE ml.ml_flag AND c.state_code = :s
ORDER BY claimants DESC
"""
