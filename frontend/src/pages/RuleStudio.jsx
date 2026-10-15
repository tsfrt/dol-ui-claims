import { Fragment, useEffect, useState } from "react";
import { BarList, CategoryBadge, Card, Gauge, Loading } from "../components/ui.jsx";
import { CATEGORY_COLORS, TECH_COLORS, ago, api, go, moneyShort, num, pct, useApi } from "../lib.js";

const STAGES = [
  "Reading Unity Catalog metadata for 10 governed tables",
  "Drafting SQL with Claude on Foundation Model APIs",
  "Compiling against the SQL warehouse",
  "Backtesting against adjudicated outcomes",
];
const LIFECYCLE = ["draft", "validated", "active"];

function Stages({ active }) {
  return (
    <div className="studio-stages">
      {STAGES.map((s, i) => (
        <div key={s} className={`studio-stage ${i < active ? "done" : i === active ? "on" : ""}`}>
          <span className="studio-stage-dot">{i < active ? "✓" : i + 1}</span>
          {s}
          {i === active && <span className="thinking" style={{ marginLeft: 8 }}><i /><i /><i /></span>}
        </div>
      ))}
    </div>
  );
}

function Lifecycle({ status }) {
  const idx = status === "retired" ? -1 : LIFECYCLE.indexOf(status);
  if (status === "retired") return <span className="badge">retired</span>;
  return (
    <div className="lifecycle">
      {LIFECYCLE.map((s, i) => (
        <span key={s} className={`lifecycle-step ${i <= idx ? "on" : ""} ${s}`}>{s}</span>
      ))}
    </div>
  );
}

function Backtest({ bt, category }) {
  const color = CATEGORY_COLORS[category] || CATEGORY_COLORS.fraud;
  return (
    <>
      <div className="studio-metrics">
        <div><div className="kpi-label">Claimants flagged</div><div className="kpi-value">{num(bt.claimants)}</div><div className="dim">{pct(bt.hit_rate)} of {num(bt.population)}</div></div>
        <div><div className="kpi-label">Benefits at risk</div><div className="kpi-value" style={{ color }}>{moneyShort(bt.at_risk)}</div><div className="dim">{num(bt.claims)} claims</div></div>
        <div style={{ textAlign: "center" }}>
          <Gauge value={bt.precision} size={120} color={bt.precision >= 0.6 ? CATEGORY_COLORS.clean : CATEGORY_COLORS.fraud} />
          <div className="dim" style={{ marginTop: -6 }}>precision vs adjudicated {category}</div>
        </div>
      </div>
      {bt.beyond_rules > 0 && (
        <div className="callout mt-s" style={{ borderColor: "rgba(96,165,250,.4)", background: "linear-gradient(90deg, rgba(96,165,250,.16), rgba(96,165,250,.03))" }}>
          <div className="big" style={{ color: TECH_COLORS.rules }}>{num(bt.beyond_rules)}</div>
          <div style={{ fontSize: 12.5 }}>
            claimants ({moneyShort(bt.beyond_rules_at_risk)}) <b>no existing rule catches</b>.
            {bt.ml_only_explained > 0 && <> {num(bt.ml_only_explained)} were previously found only by the ML model; this rule makes them explainable and deterministic.</>}
            {bt.new_claimants > 0 && <> {num(bt.new_claimants)} are caught by no technique today ({num(bt.new_bad)} adjudicated bad).</>}
          </div>
        </div>
      )}
      <h3 className="muted mt" style={{ marginBottom: 6 }}>Production validation gates</h3>
      <div className="gates">
        {bt.gates.map((g) => (
          <div key={g.id} className={`gate ${g.pass ? "pass" : "fail"}`}>
            <span className="gate-ico">{g.pass ? "✓" : "✗"}</span>
            <span style={{ flex: 1 }}>{g.label}</span>
            {g.value != null && <span className="mono">{g.id === "hits" ? num(g.value) : pct(g.value)}</span>}
          </div>
        ))}
      </div>
      <h3 className="muted mt" style={{ marginBottom: 6 }}>Flagged claimants by state</h3>
      <BarList items={bt.states.slice(0, 8).map((s) => ({ key: s.state_code, label: <span className="state-chip">{s.state_code}</span>, value: s.claimants, color }))} format={num} />
    </>
  );
}

function Draft({ result, onSaved }) {
  const [rule, setRule] = useState(result.rule);
  const [sql, setSql] = useState(result.rule.sql);
  const [bt, setBt] = useState(result.backtest);
  const [busy, setBusy] = useState(null);
  const [err, setErr] = useState(null);
  const [saved, setSaved] = useState(null);
  const edited = sql !== rule.sql;

  async function rerun() {
    setBusy("backtest"); setErr(null);
    try {
      setBt(await api("/rules/backtest", { method: "POST", body: { sql, category: rule.category } }));
      setRule({ ...rule, sql });
    } catch (e) { setErr(String(e.message).replace(/^\d+ /, "")); } finally { setBusy(null); }
  }
  async function save() {
    setBusy("save"); setErr(null);
    try {
      const r = await api("/rules/custom", { method: "POST", body: { prompt: rule.prompt, name: rule.name, category: rule.category, severity: rule.severity, rationale: rule.rationale, sql: rule.sql, author_model: rule.author_model } });
      setSaved(r);
      onSaved();
    } catch (e) { setErr(String(e.message).replace(/^\d+ /, "")); } finally { setBusy(null); }
  }
  async function promote() {
    setBusy("promote"); setErr(null);
    try {
      const r = await api(`/rules/custom/${saved.rule_id}/promote`, { method: "POST" });
      setSaved({ ...saved, status: "active", findings: r.findings });
      onSaved();
    } catch (e) { setErr(String(e.message).replace(/^\d+ /, "")); } finally { setBusy(null); }
  }

  return (
    <div className="grid g-12 mt">
      <Card className="span-7" stripe={TECH_COLORS.rules} title={<span className="row" style={{ gap: 8 }}>
          <input className="studio-name" value={rule.name} onChange={(e) => setRule({ ...rule, name: e.target.value })} />
        </span>}
        hint={<>Drafted by <span className="mono">{rule.author_model}</span> in {rule.draft_seconds}s{rule.attempts > 1 ? " · self-corrected after a compile error" : ""}</>}
        right={<div className="row"><CategoryBadge category={rule.category} />
          <select className="studio-select" value={rule.severity} onChange={(e) => setRule({ ...rule, severity: e.target.value })}>
            {["critical", "high", "medium"].map((s) => <option key={s}>{s}</option>)}
          </select></div>}>
        <div className="muted" style={{ marginBottom: 10 }}>{rule.rationale}</div>
        <textarea className="studio-sql" spellCheck={false} value={sql} onChange={(e) => setSql(e.target.value)} rows={Math.min(22, sql.split("\n").length + 1)} />
        <div className="row mt-s" style={{ gap: 8, flexWrap: "wrap" }}>
          {edited && <button className="btn sm" disabled={!!busy} onClick={rerun}>{busy === "backtest" ? "Backtesting…" : "Re-run backtest on edited SQL"}</button>}
          {!saved && <button className="btn primary" disabled={!!busy || edited} onClick={save}>{busy === "save" ? "Saving…" : bt.passed ? "Save as validated rule" : "Save as draft"}</button>}
          {saved && saved.status !== "active" && (
            <button className="btn primary" disabled={!!busy || saved.status !== "validated"} onClick={promote}>{busy === "promote" ? "Promoting…" : `Promote ${saved.rule_id} to production`}</button>
          )}
          {saved && <Lifecycle status={saved.status} />}
          {saved?.status === "active" && (
            <span className="badge clean">{num(saved.findings)} findings written to gold_custom_rule_findings · <a onClick={() => go("/cases?technique=rules")} style={{ cursor: "pointer", textDecoration: "underline" }}>open case queue</a></span>
          )}
        </div>
        {err && <div className="badge fraud mt-s" style={{ whiteSpace: "normal" }}>{err}</div>}
        <h3 className="muted mt" style={{ marginBottom: 6 }}>Sample hits (as your persona sees them)</h3>
        <table>
          <thead><tr><th>Claimant</th><th>State</th><th>Evidence</th><th className="t-right">At risk</th></tr></thead>
          <tbody>
            {bt.sample.map((s) => (
              <tr key={s.claim_id} className="click" onClick={() => go(`/cases/${s.applicant_key}`)}>
                <td style={{ fontWeight: 600, whiteSpace: "nowrap" }}>{s.name}</td>
                <td><span className="state-chip">{s.state_code}</span></td>
                <td><div className="clamp-2">{s.evidence}</div></td>
                <td className="num t-right">{moneyShort(s.amount_at_risk)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <Card className="span-5" title="Backtest" hint={`Ran in ${bt.seconds}s on the SQL warehouse, under Unity Catalog policies`}>
        <Backtest bt={bt} category={rule.category} />
      </Card>
    </div>
  );
}

function Registry({ rules, reload }) {
  const [open, setOpen] = useState(null);
  const [busy, setBusy] = useState(null);
  async function act(id, action) {
    setBusy(id);
    try { await api(`/rules/custom/${id}/${action}`, { method: "POST" }); reload(); } finally { setBusy(null); }
  }
  if (!rules.length) return <div className="empty">No analyst-authored rules yet. Draft one above.</div>;
  return (
    <table>
      <thead><tr><th>Rule</th><th>Lifecycle</th><th>Backtest precision</th><th className="t-right">Live claimants</th><th className="t-right">At risk</th><th>Author</th><th /></tr></thead>
      <tbody>
        {rules.map((r) => (
          <Fragment key={r.rule_id}>
            <tr>
              <td>
                <div className="row" style={{ gap: 8 }}><span className="mono" style={{ color: TECH_COLORS.rules }}>{r.rule_id}</span><b>{r.name}</b><CategoryBadge category={r.category} /></div>
                <div className="dim clamp-2" style={{ fontSize: 12, marginTop: 3 }}>“{r.prompt}”</div>
              </td>
              <td><Lifecycle status={r.status} /></td>
              <td className="num">{r.backtest ? pct(r.backtest.precision) : "—"}</td>
              <td className="num t-right">{r.live ? num(r.live.claimants) : "—"}</td>
              <td className="num t-right">{r.live ? moneyShort(r.live.at_risk) : "—"}</td>
              <td className="dim" style={{ fontSize: 12 }}>{r.created_by}<div>{r.promoted_at ? `promoted ${ago(r.promoted_at)}` : `created ${ago(r.created_at)}`}</div></td>
              <td className="t-right" style={{ whiteSpace: "nowrap" }}>
                <button className="btn sm ghost" onClick={() => setOpen(open === r.rule_id ? null : r.rule_id)}>{open === r.rule_id ? "Hide code" : "Pipeline code"}</button>{" "}
                {r.status === "validated" && <button className="btn sm primary" disabled={busy === r.rule_id} onClick={() => act(r.rule_id, "promote")}>Promote</button>}
                {r.status === "active" && <button className="btn sm danger" disabled={busy === r.rule_id} onClick={() => act(r.rule_id, "retire")}>Retire</button>}
              </td>
            </tr>
            {open === r.rule_id && (
              <tr>
                <td colSpan={7}>
                  <div className="dim" style={{ fontSize: 12, marginBottom: 6 }}>Equivalent entry for <span className="mono">src/pipelines/rules.py</span>, ready to land through a pull request and the preview deployment workflow.</div>
                  <pre className="studio-code">{r.snippet}</pre>
                </td>
              </tr>
            )}
          </Fragment>
        ))}
      </tbody>
    </table>
  );
}

export default function RuleStudio() {
  const { data, loading, reload } = useApi("/rules/studio");
  const [prompt, setPrompt] = useState("");
  const [stage, setStage] = useState(-1);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (stage < 0 || stage >= STAGES.length - 1) return;
    const t = setTimeout(() => setStage((s) => (s >= 0 && s < STAGES.length - 1 ? s + 1 : s)), [1200, 7000, 3500][stage] || 3000);
    return () => clearTimeout(t);
  }, [stage]);

  useEffect(() => {
    const p = new URLSearchParams(window.location.hash.split("?")[1] || "").get("prompt");
    if (p) draft(p);
  }, []);

  async function draft(text) {
    const p = (text ?? prompt).trim();
    if (!p) return;
    setPrompt(p); setResult(null); setErr(null); setStage(0);
    try {
      setResult(await api("/rules/draft", { method: "POST", body: { prompt: p } }));
    } catch (e) {
      setErr(String(e.message).replace(/^\d+ /, ""));
    } finally {
      setStage(-1);
    }
  }

  if (loading && !data) return <Loading h={500} />;
  const d = data || { rules: [], examples: [] };
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Rule studio</div>
          <h1>Describe a rule in plain English. Prove it on history. Promote it.</h1>
          <div className="sub">
            Claude on Databricks Foundation Model APIs drafts SQL grounded in Unity Catalog metadata. The draft is compiled, backtested against adjudicated outcomes, and must
            pass validation gates before an analyst can promote it into the production rule set. Definitions live in Lakebase; findings land in Unity Catalog.
          </div>
        </div>
      </div>

      <Card stripe={`linear-gradient(90deg, ${TECH_COLORS.rules}, ${TECH_COLORS.agent})`}>
        <div className="studio-compose">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => (e.metaKey || e.ctrlKey) && e.key === "Enter" && draft()}
            placeholder="e.g. Flag claimants paid by three or more states for overlapping weeks"
            rows={2}
          />
          <button className="btn primary" disabled={stage >= 0 || !prompt.trim()} onClick={() => draft()}>✦ Draft rule</button>
        </div>
        <div className="row mt-s" style={{ flexWrap: "wrap", gap: 6 }}>
          <span className="dim" style={{ fontSize: 12 }}>Try:</span>
          {d.examples.map((x) => (
            <button key={x} className="chip-btn" disabled={stage >= 0} onClick={() => draft(x)}>{x}</button>
          ))}
        </div>
        {stage >= 0 && <Stages active={stage} />}
        {err && <div className="badge fraud mt-s" style={{ whiteSpace: "normal" }}>{err}</div>}
      </Card>

      {result && <Draft key={result.rule.sql} result={result} onSaved={reload} />}

      <Card className="mt" title="Analyst rule registry" hint="custom_rules in Lakebase · active rules are re-applied by the orchestration job after every pipeline refresh">
        <Registry rules={d.rules} reload={reload} />
      </Card>
    </>
  );
}
