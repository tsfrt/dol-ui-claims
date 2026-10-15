import { useState } from "react";
import { BarList, Card, Loading, Switch, Verdict } from "../components/ui.jsx";
import { Confusion, RocCurve } from "../components/viz.jsx";
import { CATEGORY_COLORS, TECH_COLORS, ago, api, date, go, moneyShort, num, pct, useApi } from "../lib.js";

function CodeLink({ link, label = "View code" }) {
  if (!link?.url) return null;
  return (
    <a className="btn sm ghost" href={link.url} target="_blank" rel="noreferrer" title={link.path}>
      {"</>"} {label} ↗
    </a>
  );
}

export default function Detection() {
  const { data, loading, reload } = useApi("/detection");
  if (loading && !data) return <Loading h={600} />;
  if (!data) return <div className="empty">Unavailable</div>;
  const m = data.model;
  const mm = m.metrics;

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Detection Techniques</div>
          <h1>Three independent lines of defense</h1>
          <div className="sub">
            Deterministic Python rules enforce law and federal intel matches. A behavioral ML model finds organized rings that look clean claim by claim. Genie agents in Agent
            mode investigate the hardest cases like a human investigator would.
          </div>
        </div>
      </div>

      <div className="grid g-12">
        <Card className="span-12" stripe={TECH_COLORS.rules} title={<span style={{ color: TECH_COLORS.rules }}>⚖ Rules engine</span>} hint="Python rules executed in the Lakeflow pipeline against gold claims and federal intel · toggles stored in Lakebase"
          right={<CodeLink link={data.code?.rules} label="Rules code" />}>
          <div className="grid" style={{ gridTemplateColumns: "repeat(5, minmax(0,1fr))", gap: 12 }}>
            {data.rules.map((r) => (
              <RuleTile key={r.rule_id} r={r} onToggle={async (on) => { await api(`/rules/${r.rule_id}`, { method: "PUT", body: { enabled: on } }); reload(); }} />
            ))}
          </div>
        </Card>

        <Card className="span-12" stripe={TECH_COLORS.ml} title={<span style={{ color: TECH_COLORS.ml }}>◈ Behavioral fraud model</span>} hint={`${m.model_name} · version ${m.model_version} · trained ${ago(m.trained_at)} · MLflow run ${m.run_id?.slice(0, 8) || "—"}`}
          right={
            <div className="row" style={{ gap: 8 }}>
              <CodeLink link={data.code?.ml} label="Training code" />
              {m.experiment_url && <a className="btn sm" href={m.experiment_url} target="_blank" rel="noreferrer">Open in MLflow ↗</a>}
            </div>
          }>
          <div className="grid" style={{ gridTemplateColumns: "repeat(6, minmax(0,1fr))", gap: 12, marginBottom: 16 }}>
            {[["ROC AUC", mm.roc_auc?.toFixed(3)], ["PR AUC", mm.pr_auc?.toFixed(3)], ["Precision", pct(mm.precision)], ["Recall", pct(mm.recall)], ["F1", mm.f1?.toFixed(3)], ["Threshold", mm.threshold?.toFixed(2)]].map(([l, v]) => (
              <div key={l} style={{ background: "rgba(167,139,250,.07)", border: "1px solid rgba(167,139,250,.25)", borderRadius: 12, padding: 14 }}>
                <div className="kpi-label">{l}</div>
                <div className="num" style={{ fontSize: 24, fontWeight: 800, color: "#ddd6fe" }}>{v ?? "—"}</div>
              </div>
            ))}
          </div>
          <div className="grid g-12">
            <div className="span-4">
              <h3 className="muted" style={{ marginBottom: 8 }}>ROC curve (held-out 30%)</h3>
              <RocCurve points={m.roc} auc={mm.roc_auc} />
            </div>
            <div className="span-4">
              <h3 className="muted" style={{ marginBottom: 8 }}>Confusion matrix at threshold</h3>
              <Confusion tp={mm.true_positives} fp={mm.false_positives} tn={mm.true_negatives} fn={mm.false_negatives} />
              <h3 className="muted mt" style={{ marginBottom: 8 }}>Lift over rules (all claimants)</h3>
              <div className="grid" style={{ gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
                <Lift label="Rules only" v={mm.rules_only_true_fraud} c={TECH_COLORS.rules} />
                <Lift label="Both" v={mm.both_true_fraud} c="#94a3b8" />
                <Lift label="ML only" v={mm.ml_only_true_fraud} c={TECH_COLORS.ml} />
              </div>
            </div>
            <div className="span-4">
              <h3 className="muted" style={{ marginBottom: 8 }}>Permutation feature importance (ΔAUC)</h3>
              <BarList items={m.importance.map((f) => ({ key: f.feature, label: f.label, value: Math.max(0, f.importance), color: TECH_COLORS.ml }))} format={(v) => v.toFixed(3)} />
            </div>
          </div>
        </Card>

        <Card className="span-12" stripe={TECH_COLORS.agent} title={<span style={{ color: TECH_COLORS.agent }}>✦ Genie agent · Agent mode</span>} hint="Batch reviews run nightly from the orchestration job; analysts can launch on-demand investigations from any case"
          right={
            <div className="row" style={{ gap: 8 }}>
              <CodeLink link={data.code?.agent} label="Agent code" />
              <CodeLink link={data.code?.agent_review} label="Review notebook" />
              {data.agent.url && <a className="btn sm" href={data.agent.url} target="_blank" rel="noreferrer">Open Genie agent ↗</a>}
            </div>
          }>
          {data.agent.reviews.length === 0 ? (
            <div className="empty">No agent reviews yet{data.agent.space_id ? "" : ". Configure a Genie agent ID in Settings"}.</div>
          ) : (
            <div className="grid g-12">
              <div className="span-3">
                <h3 className="muted" style={{ marginBottom: 8 }}>Verdicts</h3>
                <BarList items={data.agent.verdicts.map((v) => ({ key: v.verdict, label: <Verdict verdict={v.verdict} />, value: v.n, color: v.verdict === "FRAUD" ? CATEGORY_COLORS.fraud : v.verdict === "INELIGIBLE" ? CATEGORY_COLORS.eligibility : v.verdict === "ELIGIBLE" ? CATEGORY_COLORS.clean : "#94a3b8" }))} format={num} />
                <div className="muted mt" style={{ fontSize: 12 }}>Average {data.agent.avg_queries?.toFixed(1)} SQL queries per investigation</div>
              </div>
              <div className="span-9">
                <table>
                  <thead><tr><th>Claimant</th><th>Why reviewed</th><th>Verdict</th><th>Summary</th><th>Queries</th><th>When</th></tr></thead>
                  <tbody>
                    {data.agent.reviews.map((r) => (
                      <tr key={r.applicant_key} className="click" onClick={() => go(`/cases/${r.applicant_key}`)}>
                        <td style={{ fontWeight: 600, whiteSpace: "nowrap" }}>{r.name}</td>
                        <td><span className="badge">{(r.review_bucket || "on demand").replace("_", " ")}</span></td>
                        <td><Verdict verdict={r.verdict} /></td>
                        <td style={{ width: "100%" }}><div className="clamp-2" title={r.summary}>{r.summary}</div></td>
                        <td className="num">{r.sql_count}</td>
                        <td className="dim" style={{ whiteSpace: "nowrap" }}>{ago(r.completed_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

function RuleTile({ r, onToggle }) {
  const [on, setOn] = useState(r.enabled);
  const c = CATEGORY_COLORS[r.category];
  return (
    <div style={{ background: `${c}0d`, border: `1px solid ${c}40`, borderRadius: 12, padding: 14, opacity: on ? 1 : 0.5, display: "flex", flexDirection: "column", gap: 8 }}>
      <div className="row between">
        <span className="mono" style={{ color: c, fontWeight: 700 }}>{r.rule_id}</span>
        <Switch on={on} onChange={(v) => { setOn(v); onToggle(v); }} />
      </div>
      <b style={{ fontSize: 13 }}>{r.rule_name}</b>
      <div className="muted" style={{ fontSize: 11.5, flex: 1 }}>{r.description}</div>
      <div className="dim" style={{ fontSize: 11 }}>{r.intel_source}</div>
      <div className="row between">
        <span className="num" style={{ fontSize: 20, fontWeight: 800 }}>{num(r.claimants)}</span>
        <span className="num" style={{ color: c, fontWeight: 700 }}>{moneyShort(r.at_risk)}</span>
      </div>
    </div>
  );
}

const Lift = ({ label, v, c }) => (
  <div style={{ borderRadius: 10, padding: 10, border: `1px solid ${c}55`, background: `${c}12`, textAlign: "center" }}>
    <div className="num" style={{ fontSize: 20, fontWeight: 800, color: c }}>{num(v)}</div>
    <div className="muted" style={{ fontSize: 11 }}>{label}</div>
  </div>
);
