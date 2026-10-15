import { useEffect, useRef, useState } from "react";
import { Card, CategoryBadge, Gauge, Loading, StateChip, StatusTag, Verdict } from "../components/ui.jsx";
import { ClaimTimeline, LinkGraph, Markdown } from "../components/viz.jsx";
import { CATEGORY_COLORS, TECH_COLORS, ago, api, date, go, money, num, useApi } from "../lib.js";

export default function Applicant({ id }) {
  const { data, loading, reload } = useApi(`/applicants/${id}`, { deps: [id] });
  if (loading && !data) return <Loading h={600} />;
  if (!data) return <div className="empty">Claimant not found</div>;
  const p = data.profile;
  const o = data.overall;

  return (
    <>
      <a className="muted" href="#/cases" style={{ fontSize: 12.5 }}>← Case queue</a>
      <div className="grid g-12 mt-s">
        <Card className="span-12" stripe={o.category === "fraud" ? CATEGORY_COLORS.fraud : o.category === "eligibility" ? CATEGORY_COLORS.eligibility : CATEGORY_COLORS.clean}>
          <div className="row between wrap" style={{ gap: 20 }}>
            <div className="row" style={{ gap: 16 }}>
              <div className="avatar">{`${p.first_name?.[0] || ""}${p.last_name?.[0] || ""}`}</div>
              <div>
                <div className="row" style={{ gap: 10 }}>
                  <h1 style={{ margin: 0 }}>{p.first_name} {p.last_name}</h1>
                  <StatusTag status={p.latest_status} />
                </div>
                <div className="row wrap muted mt-s" style={{ gap: 14, fontSize: 12.5 }}>
                  <span className="mono">SSN •••-••-{p.ssn_last4}</span>
                  <span>DOB {date(p.dob)}</span>
                  <span className="row" style={{ gap: 4 }}>{p.states.map((s) => <StateChip key={s} code={s} />)}</span>
                  <span>{p.claim_count} claims · {p.weeks_paid} paid weeks</span>
                  <span className="mono dim">{p.applicant_key.slice(0, 16)}</span>
                </div>
              </div>
            </div>
            <div className="row" style={{ gap: 22 }}>
              <div className={`banner ${o.category}`}>
                <div>
                  <div className="kpi-label">Combined determination</div>
                  <div className="banner-title" style={{ color: CATEGORY_COLORS[o.category] }}>{o.headline}</div>
                  <div className="muted" style={{ fontSize: 12 }}>{o.detail}</div>
                </div>
              </div>
              <Gauge value={o.risk_score} label="RISK" size={140} />
              <div>
                <div className="kpi-label">Benefits paid</div>
                <div className="num" style={{ fontSize: 22, fontWeight: 800 }}>{money(p.total_paid)}</div>
                <div className="kpi-label mt-s">At risk</div>
                <div className="num" style={{ fontSize: 22, fontWeight: 800, color: CATEGORY_COLORS.fraud }}>{money(o.at_risk)}</div>
              </div>
            </div>
          </div>
        </Card>

        <RulesCard rules={data.rules} />
        <MlCard ml={data.ml} />
        <AgentCard applicantKey={id} agent={data.agent} agentConfigured={data.agent_configured} onDone={reload} />

        <Card className="span-12" title="Claim history across states" hint="Each lane is one state claim; each block is a benefit week colored by canonical status. Federal intel events are overlaid.">
          <ClaimTimeline claims={data.claims} weeks={data.weeks} intel={data.intel} />
        </Card>

        <Card className="span-6" title="Linked identities" hint="Claimants sharing this claimant's payment account, device, or IP subnet">
          <LinkGraph links={data.links} name={`${p.first_name} ${p.last_name}`} onOpen={(k) => go(`/cases/${k}`)} />
        </Card>
        <IntelCard intel={data.intel} />

        <DecisionCard applicantKey={id} data={data} onSaved={reload} />
        <ActivityCard data={data} />
      </div>
    </>
  );
}

function TechHeader({ tech, title, sub, verdict }) {
  const c = TECH_COLORS[tech];
  return (
    <div className="tech-head">
      <div className="tech-title">
        <div className="tech-icon" style={{ background: `${c}1f`, border: `1px solid ${c}55`, color: c }}>
          {tech === "rules" ? "⚖" : tech === "ml" ? "◈" : "✦"}
        </div>
        <div>
          <h2>{title}</h2>
          <div className="muted" style={{ fontSize: 11.5 }}>{sub}</div>
        </div>
      </div>
      {verdict}
    </div>
  );
}

function RulesCard({ rules }) {
  const hits = rules.filter((r) => r.hit);
  const cat = hits.some((h) => h.category === "fraud") ? "FRAUD" : hits.length ? "INELIGIBLE" : "ELIGIBLE";
  return (
    <Card className="span-4 tech-card" stripe={TECH_COLORS.rules}>
      <TechHeader tech="rules" title="Rules engine" sub={`Python rules · ${hits.length} of ${rules.length} triggered`} verdict={<Verdict verdict={cat} />} />
      <div>
        {rules.map((r) => (
          <div key={r.rule_id} className="check">
            <span className={`check-ico ${!r.enabled ? "off" : r.hit ? `hit ${r.category}` : "pass"}`}>{!r.enabled ? "–" : r.hit ? "!" : "✓"}</span>
            <div className="row between" style={{ gap: 8 }}>
              <span style={{ fontWeight: r.hit ? 700 : 500, color: r.hit ? "var(--text)" : "var(--muted)" }}>{r.rule_name}</span>
              <span className="dim mono">{r.rule_id}</span>
            </div>
            {r.hit && (
              <div className={`evidence ${r.category}`}>
                {r.evidence}
                <div className="dim" style={{ fontSize: 11, marginTop: 3 }}>{r.intel_source}{r.state_code ? ` · ${r.state_code}` : ""}{r.amount_at_risk ? ` · ${money(r.amount_at_risk)} at risk` : ""}</div>
              </div>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}

function MlCard({ ml }) {
  if (!ml) return <Card className="span-4 tech-card" stripe={TECH_COLORS.ml}><TechHeader tech="ml" title="ML model" sub="Not scored yet" /></Card>;
  const v = ml.flag ? "FRAUD" : "ELIGIBLE";
  return (
    <Card className="span-4 tech-card" stripe={TECH_COLORS.ml}>
      <TechHeader tech="ml" title="ML fraud model" sub={`Gradient boosting · v${ml.model_version} · threshold ${Math.round(ml.threshold * 100)}`} verdict={<Verdict verdict={v} />} />
      <div className="row" style={{ justifyContent: "center" }}>
        <Gauge value={ml.score} label={`${ml.risk_band.toUpperCase()} RISK`} color={TECH_COLORS.ml} size={170} />
      </div>
      <div>
        <h3 className="muted" style={{ marginBottom: 8 }}>Why the model scored this claimant</h3>
        <div className="grid" style={{ gap: 6 }}>
          {ml.drivers.map((d) => (
            <div key={d} className="row" style={{ gap: 8, fontSize: 12.5 }}>
              <span style={{ width: 6, height: 6, borderRadius: 6, background: TECH_COLORS.ml, flex: "none" }} />
              {d}
            </div>
          ))}
        </div>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {ml.features.map((f) => (
          <div key={f.name} style={{ background: "rgba(167,139,250,.06)", border: "1px solid rgba(167,139,250,.18)", borderRadius: 8, padding: "6px 9px" }}>
            <div className="dim" style={{ fontSize: 10.5 }}>{f.label}</div>
            <div className="num" style={{ fontWeight: 700, color: f.elevated ? "#c4b5fd" : "var(--text)" }}>{f.display}</div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function AgentCard({ applicantKey, agent, agentConfigured, onDone }) {
  const [run, setRun] = useState(null);
  const [err, setErr] = useState(null);
  const timer = useRef();
  const live = run && run.status === "running";
  const shown = run?.status === "completed" ? run.result : agent;

  useEffect(() => () => clearInterval(timer.current), []);

  async function start() {
    setErr(null);
    try {
      const r = await api(`/applicants/${applicantKey}/investigate`, { method: "POST" });
      setRun({ status: "running", steps: [], run_id: r.run_id });
      timer.current = setInterval(async () => {
        const s = await api(`/investigations/${r.run_id}`);
        setRun(s);
        if (s.status !== "running") {
          clearInterval(timer.current);
          if (s.status === "failed") setErr(s.error);
          else onDone && onDone();
        }
      }, 2000);
    } catch (e) {
      setErr(String(e.message || e));
    }
  }

  const steps = live ? run.steps : shown?.steps || [];
  return (
    <Card className="span-4 tech-card" stripe={TECH_COLORS.agent}>
      <TechHeader
        tech="agent"
        title="Genie agent"
        sub={shown ? `Agent mode · ${shown.sql_count} queries · ${ago(shown.completed_at)}` : "Agent mode investigation"}
        verdict={shown && !live ? <Verdict verdict={shown.verdict} /> : null}
      />
      {shown && !live && (
        <div style={{ background: "rgba(34,211,238,.06)", border: "1px solid rgba(34,211,238,.25)", borderRadius: 10, padding: "10px 12px" }}>
          <div className="row between">
            <span className="kpi-label" style={{ color: TECH_COLORS.agent }}>Agent summary</span>
            <span className="badge agent">{shown.confidence} confidence</span>
          </div>
          <div style={{ marginTop: 6, fontSize: 13 }}>{shown.summary}</div>
        </div>
      )}
      {live && (
        <div className="row" style={{ gap: 10, color: TECH_COLORS.agent }}>
          <span className="thinking"><i /><i /><i /></span>
          Agent is planning and running queries across claims, intel, and identity links…
        </div>
      )}
      {steps.length > 0 && (
        <div>
          <h3 className="muted" style={{ marginBottom: 8 }}>Investigation trace</h3>
          <div className="steps">
            {steps.map((s, i) => (
              <div key={i} className="step">
                <span className="step-ico">{s.kind === "sql" ? "⌕" : s.kind === "result" ? "▤" : "✦"}</span>
                <div style={{ minWidth: 0 }}>
                  {s.kind === "sql" ? <b>{s.title || "SQL query"}</b> : s.kind === "result" ? <span className="muted">Result</span> : <span className="muted">Reasoning</span>}
                  {s.kind === "sql" && s.sql && <pre>{s.sql}</pre>}
                  {s.kind === "reasoning" && <div style={{ fontSize: 12, color: "#c9d3ea" }}>{s.text}</div>}
                  {s.kind === "result" && <pre style={{ color: "#cbd5e1" }}>{s.text.slice(0, 500)}</pre>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {shown?.report && !live && (
        <details>
          <summary style={{ cursor: "pointer", color: TECH_COLORS.agent, fontWeight: 600 }}>Full investigator report</summary>
          <Markdown text={shown.report} />
        </details>
      )}
      {!shown && !live && <div className="muted" style={{ fontSize: 12.5 }}>No agent review yet. Agent mode plans a multi-step investigation, writes and runs SQL across Unity Catalog, and returns a verdict with evidence.</div>}
      {err && <div className="evidence" style={{ gridColumn: "auto" }}>{err}</div>}
      <div style={{ marginTop: "auto" }}>
        <button className="btn primary" onClick={start} disabled={live || !agentConfigured}>
          ✦ {live ? "Investigating…" : shown ? "Re-run Agent mode investigation" : "Run Agent mode investigation"}
        </button>
        {!agentConfigured && <div className="dim mt-s" style={{ fontSize: 11.5 }}>Set a Genie agent ID in Settings to enable.</div>}
      </div>
    </Card>
  );
}

function IntelCard({ intel }) {
  const items = [
    { src: "SSA Death Master File", hit: !!intel.death, text: intel.death ? `Date of death ${date(intel.death.date_of_death)}` : "No death record", cat: "fraud" },
    { src: "Bureau of Prisons SENTRY", hit: intel.inmates.some((i) => i.active_during_claim), text: intel.inmates.length ? intel.inmates.map((i) => `${i.facility}: ${date(i.admit_date)} – ${i.release_date ? date(i.release_date) : "present"}`).join("; ") : "No custody record", cat: "fraud", note: intel.inmates.length && !intel.inmates.some((i) => i.active_during_claim) ? "Released before claim" : null },
    { src: "SSA Identity Verification", hit: intel.identity && intel.identity.verification_code !== "MATCH", text: intel.identity ? (intel.identity.verification_code === "MATCH" ? "Name and DOB match SSA" : `SSA record: ${intel.identity.first_name} ${intel.identity.last_name}, DOB ${date(intel.identity.dob)}`) : "No record", cat: "fraud" },
    { src: "Treasury Do Not Pay", hit: intel.dnp.length > 0, text: intel.dnp.length ? intel.dnp.map((d) => `${d.list_name}: ${d.reason}`).join("; ") : "Not listed", cat: "fraud" },
    { src: "HHS NDNH quarterly wages", hit: intel.wages.some((w) => w.overlaps_claim), text: `${intel.wages.length} wage records · ${money(intel.wages.reduce((a, w) => a + w.wages, 0))}`, cat: "fraud", rows: intel.wages },
  ];
  return (
    <Card className="span-6" title="Federal intel cross-match" hint="Matched on SSN hash across five federal data sources">
      <div className="grid" style={{ gap: 8 }}>
        {items.map((i) => (
          <div key={i.src} className="row" style={{ gap: 12, padding: "10px 12px", borderRadius: 10, background: i.hit ? "rgba(255,77,109,.08)" : "rgba(255,255,255,.02)", border: `1px solid ${i.hit ? "rgba(255,77,109,.35)" : "var(--line)"}` }}>
            <span className={`check-ico ${i.hit ? "hit" : "pass"}`}>{i.hit ? "!" : "✓"}</span>
            <div style={{ minWidth: 0, flex: 1 }}>
              <div className="row between">
                <b style={{ fontSize: 12.5 }}>{i.src}</b>
                {i.hit ? <span className="badge fraud">Match</span> : i.note ? <span className="badge">{i.note}</span> : <span className="badge clean">Clear</span>}
              </div>
              <div className="muted" style={{ fontSize: 12 }}>{i.text}</div>
              {i.rows && i.rows.length > 0 && (
                <div className="row wrap mt-s" style={{ gap: 4 }}>
                  {i.rows.map((w) => (
                    <span key={w.quarter + w.employer_name} className={`badge ${w.overlaps_claim ? "eligibility" : ""}`} title={w.employer_name}>
                      {w.quarter} · {money(w.wages)}{w.overlaps_claim ? " · during claim" : ""}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

const DECISIONS = [
  ["confirmed_fraud", "Confirm fraud", "danger"],
  ["ineligible", "Ineligible · overpayment", "warn"],
  ["refer_oig", "Refer to DOL OIG", "danger"],
  ["cleared", "Clear claimant", "ok"],
];

function DecisionCard({ applicantKey, data, onSaved }) {
  const [rationale, setRationale] = useState("");
  const [saving, setSaving] = useState(null);
  const [msg, setMsg] = useState(null);
  const last = data.dispositions[0];

  async function decide(decision) {
    setSaving(decision);
    try {
      await api(`/applicants/${applicantKey}/disposition`, { method: "POST", body: { decision, rationale } });
      setRationale("");
      setMsg("Disposition saved to Lakebase");
      onSaved();
    } catch (e) {
      setMsg(String(e.message || e));
    } finally {
      setSaving(null);
      setTimeout(() => setMsg(null), 3000);
    }
  }

  return (
    <Card className="span-6" title="Analyst determination" hint="Written to Lakebase (Postgres) · feeds model retraining labels" right={<span className="badge">{data.case?.status?.replace("_", " ") || "new"}</span>}>
      {last && (
        <div className="row" style={{ gap: 10, marginBottom: 12, padding: "10px 12px", borderRadius: 10, background: "rgba(255,255,255,.03)", border: "1px solid var(--line)" }}>
          <span className={`badge ${last.decision === "cleared" ? "clean" : last.decision === "ineligible" ? "eligibility" : "fraud"}`}>{last.decision.replace("_", " ")}</span>
          <span className="muted" style={{ fontSize: 12 }}>{last.analyst} · {ago(last.created_at)}</span>
          <span style={{ fontSize: 12.5 }}>{last.rationale}</span>
        </div>
      )}
      <label className="field">
        Rationale
        <textarea value={rationale} onChange={(e) => setRationale(e.target.value)} placeholder="Summarize the evidence supporting your determination" />
      </label>
      <div className="row wrap mt" style={{ gap: 8 }}>
        {DECISIONS.map(([k, label, tone]) => (
          <button key={k} className={`btn ${tone}`} disabled={!!saving} onClick={() => decide(k)}>{saving === k ? "Saving…" : label}</button>
        ))}
      </div>
      {msg && <div className="toast">{msg}</div>}
    </Card>
  );
}

function ActivityCard({ data }) {
  const [body, setBody] = useState("");
  const [notes, setNotes] = useState(data.notes);
  useEffect(() => setNotes(data.notes), [data.notes]);
  async function add() {
    if (!body.trim()) return;
    const n = await api(`/applicants/${data.profile.applicant_key}/notes`, { method: "POST", body: { body } });
    setNotes([n, ...notes]);
    setBody("");
  }
  const feed = [
    ...notes.map((n) => ({ t: n.created_at, who: n.author, text: n.body, kind: "note" })),
    ...data.dispositions.map((d) => ({ t: d.created_at, who: d.analyst, text: `Disposition: ${d.decision.replace("_", " ")}${d.rationale ? ` · ${d.rationale}` : ""}`, kind: "decision" })),
    ...data.investigations.map((r) => ({ t: r.created_at, who: r.requested_by, text: `Genie Agent mode investigation · ${r.status}${r.verdict ? ` · ${r.verdict}` : ""}`, kind: "agent" })),
  ].sort((a, b) => new Date(b.t) - new Date(a.t));
  return (
    <Card className="span-6" title="Case activity" hint="Notes, determinations, and agent runs (Lakebase)">
      <div className="row" style={{ gap: 8 }}>
        <input value={body} onChange={(e) => setBody(e.target.value)} placeholder="Add a case note" onKeyDown={(e) => e.key === "Enter" && add()} />
        <button className="btn" onClick={add}>Add</button>
      </div>
      <div className="grid mt" style={{ gap: 10, maxHeight: 260, overflow: "auto" }}>
        {feed.length === 0 && <div className="dim" style={{ fontSize: 12.5 }}>No activity yet</div>}
        {feed.map((f, i) => (
          <div key={i} className="row" style={{ gap: 10, alignItems: "flex-start" }}>
            <span className="step-ico" style={f.kind === "decision" ? { background: "rgba(255,77,109,.12)", color: "#ff4d6d", borderColor: "rgba(255,77,109,.35)" } : f.kind === "note" ? { background: "rgba(96,165,250,.12)", color: "#60a5fa", borderColor: "rgba(96,165,250,.35)" } : undefined}>
              {f.kind === "decision" ? "⚑" : f.kind === "note" ? "✎" : "✦"}
            </span>
            <div style={{ fontSize: 12.5 }}>
              <div>{f.text}</div>
              <div className="dim" style={{ fontSize: 11 }}>{f.who} · {ago(f.t)}</div>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
