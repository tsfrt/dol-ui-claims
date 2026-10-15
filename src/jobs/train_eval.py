"""Train and evaluate the behavioral fraud model, then score every claimant.

The model sees only behavioral signals (shared bank accounts, devices, IP
subnets, employer concentration, wage-history shape, benefit levels). It never
sees intel matches or rule outputs, so it complements the rules engine and finds
organized rings that no single deterministic rule can.
"""

import argparse
from datetime import datetime, timezone

import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from mlflow.models import infer_signature
from pyspark.sql import SparkSession
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score, roc_curve
from sklearn.model_selection import train_test_split

parser = argparse.ArgumentParser()
parser.add_argument("--catalog", default="lanl")
parser.add_argument("--schema", default="dol_ui")
args, _ = parser.parse_known_args()
ns = f"{args.catalog}.{args.schema}"
spark = SparkSession.builder.getOrCreate()

FEATURES = {
    "shared_bank_claimants": "Claimants sharing the payment account",
    "shared_device_claimants": "Claimants sharing the filing device",
    "shared_subnet_claimants": "Claimants filing from the same IP subnet",
    "employer_claimants": "Claimants citing the same last employer",
    "base_quarters_with_wages": "Base-period quarters with reported wages",
    "high_quarter_share": "Share of base wages earned in one quarter",
    "wba_to_state_max": "Weekly benefit as share of state maximum",
    "claim_count": "Claims filed",
    "state_count": "States claimed in",
    "avg_work_search": "Average weekly work search contacts",
}

features = spark.sql(f"""
WITH links AS (
  SELECT l.link_type, k AS applicant_key, l.applicant_count
  FROM {ns}.gold_identity_links l LATERAL VIEW explode(l.applicant_keys) t AS k
),
link_feats AS (
  SELECT applicant_key,
    max(CASE WHEN link_type = 'bank_account' THEN applicant_count END) AS shared_bank_claimants,
    max(CASE WHEN link_type = 'device' THEN applicant_count END) AS shared_device_claimants,
    max(CASE WHEN link_type = 'ip_subnet' THEN applicant_count END) AS shared_subnet_claimants
  FROM links GROUP BY applicant_key
),
emp AS (
  SELECT employer_name, count(DISTINCT applicant_key) AS n FROM {ns}.gold_claims GROUP BY employer_name
),
claim_feats AS (
  SELECT c.applicant_key,
    max(e.n) AS employer_claimants,
    max(c.weekly_benefit_amount / p.max_wba) AS wba_to_state_max,
    min(c.first_week) AS first_week
  FROM {ns}.gold_claims c
  JOIN emp e ON c.employer_name = e.employer_name
  JOIN {ns}.ref_state_programs p ON c.state_code = p.state_code
  GROUP BY c.applicant_key
),
ws AS (
  SELECT applicant_key, avg(work_search_contacts) AS avg_work_search
  FROM {ns}.gold_claim_weeks WHERE status = 'paid' GROUP BY applicant_key
),
wages AS (
  SELECT cf.applicant_key,
    count(DISTINCT w.quarter) AS base_quarters_with_wages,
    max(w.wages) / nullif(sum(w.wages), 0) AS high_quarter_share
  FROM claim_feats cf
  JOIN {ns}.intel_ndnh_quarterly_wages w ON w.ssn_hash = cf.applicant_key
  WHERE w.quarter_start < cf.first_week AND w.quarter_start >= add_months(cf.first_week, -18)
  GROUP BY cf.applicant_key
)
SELECT p.applicant_key, p.claim_count, p.state_count,
  coalesce(lf.shared_bank_claimants, 1) AS shared_bank_claimants,
  coalesce(lf.shared_device_claimants, 1) AS shared_device_claimants,
  coalesce(lf.shared_subnet_claimants, 1) AS shared_subnet_claimants,
  cf.employer_claimants, cf.wba_to_state_max,
  coalesce(w.base_quarters_with_wages, 0) AS base_quarters_with_wages,
  coalesce(w.high_quarter_share, 1.0) AS high_quarter_share,
  coalesce(ws.avg_work_search, 0) AS avg_work_search,
  coalesce(a.label_fraud, 0) AS label
FROM {ns}.gold_applicant_profile p
LEFT JOIN link_feats lf USING (applicant_key)
LEFT JOIN claim_feats cf USING (applicant_key)
LEFT JOIN wages w USING (applicant_key)
LEFT JOIN ws USING (applicant_key)
LEFT JOIN {ns}.ref_applicants a USING (applicant_key)
""").toPandas()

cols = list(FEATURES)
X = features[cols].astype(float).fillna(0.0)
y = features["label"].astype(int)
X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.3, random_state=42, stratify=y)

user = spark.sql("SELECT current_user() AS u").collect()[0]["u"]
mlflow.set_tracking_uri("databricks")
mlflow.set_registry_uri("databricks-uc")
mlflow.set_experiment(f"/Users/{user}/dol_ui_fraud")
model_name = f"{ns}.ui_fraud_ring_model"

params = {"max_iter": 300, "learning_rate": 0.06, "max_leaf_nodes": 15, "l2_regularization": 1.0, "random_state": 42}
with mlflow.start_run(run_name="behavioral_fraud_gbm") as run:
    model = HistGradientBoostingClassifier(**params).fit(X_tr, y_tr)
    p_te = model.predict_proba(X_te)[:, 1]

    thresholds = np.linspace(0.2, 0.9, 71)
    f1s = [f1_score(y_te, (p_te >= t).astype(int)) for t in thresholds]
    threshold = float(thresholds[int(np.argmax(f1s))])
    pred = (p_te >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_te, pred).ravel()

    metrics = {
        "roc_auc": roc_auc_score(y_te, p_te),
        "pr_auc": average_precision_score(y_te, p_te),
        "precision": precision_score(y_te, pred),
        "recall": recall_score(y_te, pred),
        "f1": f1_score(y_te, pred),
        "threshold": threshold,
        "test_rows": float(len(y_te)),
        "train_rows": float(len(y_tr)),
        "fraud_rate": float(y.mean()),
    }
    mlflow.log_params(params)
    mlflow.log_metrics(metrics)

    imp = permutation_importance(model, X_te, y_te, scoring="roc_auc", n_repeats=8, random_state=7)
    importance = pd.DataFrame({"feature": cols, "label": [FEATURES[c] for c in cols], "importance": imp.importances_mean}).sort_values("importance", ascending=False)
    mlflow.log_table(importance, "feature_importance.json")

    signature = infer_signature(X_tr, model.predict_proba(X_tr)[:, 1])
    model_version = "unregistered"
    try:
        info = mlflow.sklearn.log_model(model, artifact_path="model", signature=signature, input_example=X_tr.head(5), registered_model_name=model_name)
        model_version = str(getattr(info, "registered_model_version", None) or "1")
    except Exception as e:
        print(f"Model registration skipped: {e}")
        mlflow.sklearn.log_model(model, artifact_path="model", signature=signature)
    run_id = run.info.run_id

fpr, tpr, thr = roc_curve(y_te, p_te)
idx = np.unique(np.linspace(0, len(fpr) - 1, 60).astype(int))
roc = pd.DataFrame({"fpr": fpr[idx], "tpr": tpr[idx], "threshold": np.clip(thr[idx], 0, 1)})

features["ml_score"] = model.predict_proba(X)[:, 1]

clean = features[features["label"] == 0]
p95 = {c: float(clean[c].quantile(0.95)) for c in cols}


def drivers(r):
    out = []
    if r.shared_bank_claimants >= 3:
        out.append(f"Payment account shared with {int(r.shared_bank_claimants) - 1} other claimants")
    if r.shared_device_claimants >= 3:
        out.append(f"Filing device used by {int(r.shared_device_claimants) - 1} other claimants")
    if r.shared_subnet_claimants >= 3:
        out.append(f"IP subnet shared with {int(r.shared_subnet_claimants) - 1} other claimants")
    if r.base_quarters_with_wages <= 1 and r.high_quarter_share >= 0.99:
        out.append("All base-period wages reported in a single quarter")
    if r.employer_claimants >= 5 and r.base_quarters_with_wages <= 1:
        out.append(f"Employer cited by {int(r.employer_claimants)} claimants with thin wage history")
    if r.wba_to_state_max >= 0.99:
        out.append("Weekly benefit at the state maximum")
    if r.state_count > 1:
        out.append(f"Claims in {int(r.state_count)} states")
    if not out:
        top = max(cols, key=lambda c: (r[c] - p95[c]) / (abs(p95[c]) + 1e-6))
        out.append(f"{FEATURES[top]}: {r[top]:.2f}")
    return out[:4]


features["drivers"] = features.apply(drivers, axis=1)
bins = [-0.01, min(0.3, threshold - 0.01), threshold, max(0.9, threshold + 0.01), 1.01]
features["risk_band"] = pd.cut(features["ml_score"], bins, labels=["low", "elevated", "high", "critical"]).astype(str)
scored_at = datetime.now(timezone.utc)

scores = spark.createDataFrame(features[["applicant_key", "ml_score", "risk_band", "drivers"] + cols].assign(model_version=model_version, run_id=run_id, scored_at=scored_at))
scores.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{ns}.gold_ml_scores")

spark.sql(f"""
CREATE OR REPLACE TABLE {ns}.gold_ml_findings AS
SELECT applicant_key, 'ml' AS finding_source, 'ML-01' AS rule_id, 'Behavioral fraud pattern' AS rule_name, 'fraud' AS category,
  CASE WHEN ml_score >= 0.9 THEN 'critical' ELSE 'high' END AS severity, ml_score AS score,
  array_join(drivers, '; ') AS evidence, model_version, scored_at AS checked_at
FROM {ns}.gold_ml_scores WHERE ml_score >= {threshold}
""")

rules_flagged = {r[0] for r in spark.sql(f"SELECT DISTINCT applicant_key FROM {ns}.gold_check_findings WHERE category = 'fraud'").collect()}
ml_flag = features["ml_score"] >= threshold
truth = features["label"] == 1
in_rules = features["applicant_key"].isin(rules_flagged)
metrics.update({
    "ml_only_true_fraud": float((ml_flag & truth & ~in_rules).sum()),
    "rules_only_true_fraud": float((~ml_flag & truth & in_rules).sum()),
    "both_true_fraud": float((ml_flag & truth & in_rules).sum()),
    "missed_fraud": float((~ml_flag & truth & ~in_rules).sum()),
    "true_negatives": float(tn), "false_positives": float(fp), "false_negatives": float(fn), "true_positives": float(tp),
})

meta = dict(run_id=run_id, model_name=model_name, model_version=model_version, trained_at=scored_at)
spark.createDataFrame(pd.DataFrame([{"metric": k, "value": float(v), **meta} for k, v in metrics.items()])).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{ns}.ml_model_metrics")
spark.createDataFrame(roc.assign(**meta)).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{ns}.ml_roc_curve")
spark.createDataFrame(importance.assign(**meta)).write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{ns}.ml_feature_importance")
for legacy in ("ml_metrics",):
    spark.sql(f"DROP TABLE IF EXISTS {ns}.{legacy}")
print({k: round(v, 4) for k, v in metrics.items()})
