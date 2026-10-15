import { useEffect, useState } from "react";
import USMap from "../components/USMap.jsx";
import { BarList, Card, Json, Kpi, Loading, StateChip, StatusTag, TechDots, Verdict, RiskBar } from "../components/ui.jsx";
import { CATEGORY_COLORS, TECH_COLORS, go, money, moneyShort, num, pct, time, useApi } from "../lib.js";

const FORMAT_LABEL = {
  ssn_format: { dashed: "SSN 123-45-6789", plain: "SSN 123456789" },
  date_format: { iso: "Dates YYYY-MM-DD", us: "Dates MM/DD/YYYY" },
  week_format: { iso: "Weeks as dates", us: "Weeks MM/DD/YYYY", yyyyww: "Weeks YYYYWW" },
  amount_unit: { dollars: "Amounts in dollars", cents: "Amounts in cents", currency_string: 'Amounts as "$1,234.00"' },
};

export default function Command() {
  const { data, loading } = useApi("/overview", { refresh: 30000 });
  const [selected, setSelected] = useState(null);
  useEffect(() => {
    if (!selected && data?.states?.length) setSelected([...data.states].sort((a, b) => b.at_risk - a.at_risk)[0].state_code);
  }, [data, selected]);

  if (loading && !data) return <Skeleton />;
  if (!data) return <div className="empty">Overview unavailable</div>;
  const k = data.kpis;
  const t = data.techniques;

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Unemployment Insurance Integrity · {k.states || 11} State Workforce Agencies</div>
          <h1>National Claims Integrity Command Center</h1>
          <div className="sub">
            State UI systems push claim status events through <b>Zerobus</b>, drop batch extracts that <b>Auto Loader</b> pulls, or share their own Databricks tables through <b>Delta Sharing</b>. Lakeflow pipelines normalize {k.states || 11} inconsistent schemas, cross-match federal intel, and
            three independent detection techniques (<span style={{ color: TECH_COLORS.rules }}>Python rules</span>, <span style={{ color: TECH_COLORS.ml }}>ML model</span>,{" "}
            <span style={{ color: TECH_COLORS.agent }}>Genie Agent mode</span>) flag fraud and ineligibility before the next payment.
          </div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <span className="badge clean"><span className="dot" /> Zerobus push</span>
          <span className="badge clean"><span className="dot" /> Auto Loader pull{k.files ? ` · ${k.files} files` : ""}</span>
          <span className="badge clean"><span className="dot" /> Delta Sharing{k.share_states ? ` · ${k.share_states} states` : ""}</span>
          <span className="badge">Updated {time(data.updated_at)}</span>
        </div>
      </div>

      <div className="kpis">
        <Kpi label="Claim events ingested" value={num(k.events)} foot={`${num(k.claims)} claims · ${k.states} states · ${num(k.file_events)} via file drop · ${num(k.share_events)} via Delta Sharing`} />
        <Kpi label="Claimants resolved" value={num(k.claimants)} foot={`${num(k.multi_state)} claim in 2+ states`} />
        <Kpi label="Benefits paid" value={moneyShort(k.total_paid)} foot={`${num(k.weeks_paid)} paid weeks`} />
        <Kpi label="Flagged claimants" value={num(k.flagged)} foot={`${pct(k.flag_rate)} of claimants`} tone="warn" />
        <Kpi label="Improper payments at risk" value={moneyShort(k.at_risk)} foot={`${pct(k.at_risk / (k.total_paid || 1))} of benefits paid`} tone="hot" />
        <Kpi label="Fraud · Ineligible" value={<><span style={{ color: CATEGORY_COLORS.fraud }}>{num(k.fraud)}</span><span className="dim"> · </span><span style={{ color: CATEGORY_COLORS.eligibility }}>{num(k.ineligible)}</span></>} foot="claimants by finding type" />
      </div>

      <div className="grid g-12">
        <Card
          className="span-8"
          title="Where improper payments are concentrated"
          hint="State fill = share of claimants flagged · arcs = same claimant paid by two states for overlapping weeks · click a state"
          right={
            <div className="legend">
              <span className="row" style={{ gap: 6 }}>Low<span className="ramp" />High</span>
              <span className="row" style={{ gap: 6 }}><i style={{ width: 18, height: 3, background: "#ff4d6d", display: "inline-block" }} />Interstate duplicates</span>
            </div>
          }
        >
          <USMap states={data.states} pairs={data.pairs} selected={selected} onSelect={setSelected} />
        </Card>

        <div className="span-4 grid" style={{ alignContent: "start" }}>
          <Card title="Detection coverage" hint="Claimants flagged by each technique">
            <div className="grid" style={{ gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
              {[
                ["rules", "Rules", t.rules, "Python · 10 rules"],
                ["ml", "ML model", t.ml, `AUC ${t.ml_auc ? t.ml_auc.toFixed(2) : "—"}`],
                ["agent", "Genie agent", t.agent, `${num(t.agent_reviews)} reviewed`],
              ].map(([key, label, v, foot]) => (
                <div key={key} style={{ background: `${TECH_COLORS[key]}14`, border: `1px solid ${TECH_COLORS[key]}44`, borderRadius: 12, padding: "12px 12px 10px" }}>
                  <div style={{ fontSize: 11, color: TECH_COLORS[key], fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.8 }}>{label}</div>
                  <div className="num" style={{ fontSize: 24, fontWeight: 800, marginTop: 2 }}>{num(v)}</div>
                  <div className="muted" style={{ fontSize: 11 }}>{foot}</div>
                </div>
              ))}
            </div>
            <div className="mt">
              <div className="row between" style={{ fontSize: 11.5, marginBottom: 6 }}>
                <span style={{ color: TECH_COLORS.rules }}>Rules only {num(t.rules_only)}</span>
                <span className="muted">Both {num(t.both)}</span>
                <span style={{ color: TECH_COLORS.ml }}>ML only {num(t.ml_only)}</span>
              </div>
              <div style={{ display: "flex", height: 12, borderRadius: 6, overflow: "hidden", gap: 2 }}>
                <span style={{ flex: t.rules_only || 0.01, background: TECH_COLORS.rules }} />
                <span style={{ flex: t.both || 0.01, background: "linear-gradient(90deg,#60a5fa,#a78bfa)" }} />
                <span style={{ flex: t.ml_only || 0.01, background: TECH_COLORS.ml }} />
              </div>
            </div>
            <div className="callout mt">
              <div className="big">{num(t.ml_only)}</div>
              <div style={{ fontSize: 12.5 }}>
                claimants surfaced <b>only by the ML model</b>: organized rings sharing bank accounts, devices, and shell employers that pass every individual rule.{" "}
                <span style={{ color: "#c4b5fd", fontWeight: 700 }}>{moneyShort(t.ml_only_paid)}</span> paid.
              </div>
            </div>
          </Card>

          <Card title="Findings by type" hint="Claimants flagged · dollars at risk">
            <div className="row" style={{ gap: 6, marginBottom: 8 }}>
              <span className="badge fraud">Fraud</span>
            </div>
            <BarList
              items={data.findings.filter((f) => f.category === "fraud").map((f) => ({ key: f.rule_id, label: <span>{f.rule_name} <span className="dim mono">{f.technique === "ml" ? "ML" : f.rule_id}</span></span>, value: f.claimants, extra: moneyShort(f.at_risk), color: f.technique === "ml" ? TECH_COLORS.ml : CATEGORY_COLORS.fraud }))}
              format={num}
            />
            <div className="row mt" style={{ gap: 6, marginBottom: 8 }}>
              <span className="badge eligibility">Eligibility</span>
            </div>
            <BarList
              items={data.findings.filter((f) => f.category === "eligibility").map((f) => ({ key: f.rule_id, label: <span>{f.rule_name} <span className="dim mono">{f.rule_id}</span></span>, value: f.claimants, extra: moneyShort(f.at_risk), color: CATEGORY_COLORS.eligibility }))}
              format={num}
            />
          </Card>
        </div>

        {selected && <StatePanel code={selected} summary={data.states.find((s) => s.state_code === selected)} />}

        <LiveFeed />
        <TopCases cases={data.top_cases} />
      </div>
    </>
  );
}

function StatePanel({ code, summary }) {
  const { data } = useApi(`/states/${code}`, { deps: [code] });
  const spec = data?.spec;
  return (
    <Card
      className="span-12"
      stripe="linear-gradient(90deg,#22d3ee,#a78bfa,#ff4d6d)"
      title={
        <span className="row" style={{ gap: 10 }}>
          <StateChip code={code} /> {summary?.state_name} · {summary?.agency}
        </span>
      }
      hint={`${summary?.system || ""} · ${num(summary?.events)} events via ${summary?.channel || "Zerobus"} · ${num(summary?.claimants)} claimants · ${money(summary?.total_paid)} paid`}
      right={<button className="btn sm" onClick={() => go(`/cases?state=${code}`)}>Open {code} case queue →</button>}
    >
      {!data ? (
        <Loading h={220} />
      ) : (
        <div className="grid g-12">
          <div className="span-4">
            <h3 className="muted" style={{ marginBottom: 8 }}>Raw payload as sent by {code}</h3>
            <Json value={data.sample_payload} />
          </div>
          <div className="span-4">
            <h3 className="muted" style={{ marginBottom: 8 }}>Status vocabulary → canonical</h3>
            <div className="grid" style={{ gap: 6 }}>
              {Object.entries(spec.status_codes).map(([canon, raw]) => (
                <div key={canon} className="row" style={{ gap: 10 }}>
                  <span className="raw" style={{ minWidth: 150 }}>{JSON.stringify(raw)}</span>
                  <span className="dim">→</span>
                  <StatusTag status={canon} />
                  <span className="muted num" style={{ marginLeft: "auto", fontSize: 12 }}>{num(data.status_mix.find((s) => s.status === canon)?.claims || 0)} claims</span>
                </div>
              ))}
            </div>
            <div className="row wrap mt" style={{ gap: 6 }}>
              {Object.keys(FORMAT_LABEL).map((f) => (
                <span key={f} className="badge">{FORMAT_LABEL[f][spec[f]] || spec[f]}</span>
              ))}
              {spec.week_anchor === "end" && <span className="badge">Week-ending dates</span>}
              <span className="badge">Max WBA ${spec.max_wba}</span>
              <span className="badge">{spec.max_weeks} week max</span>
            </div>
            <div className="mt">
              <h3 className="muted" style={{ marginBottom: 6 }}>Field mapping</h3>
              <div className="mono" style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "3px 12px", fontSize: 11.5 }}>
                {["ssn", "first_name", "week", "wba", "separation", "work_search", "bank_token"].map((f) => (
                  <FragmentRow key={f} a={spec.fields[f]} b={f} />
                ))}
              </div>
            </div>
          </div>
          <div className="span-4">
            <h3 className="muted" style={{ marginBottom: 8 }}>{code} findings</h3>
            {data.findings.length ? (
              <BarList
                items={data.findings.map((f) => ({ key: f.rule_id, label: f.rule_name, value: f.claimants, extra: moneyShort(f.at_risk), color: f.technique === "ml" ? TECH_COLORS.ml : CATEGORY_COLORS[f.category] }))}
                format={num}
              />
            ) : (
              <div className="empty">No findings</div>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

const FragmentRow = ({ a, b }) => (
  <>
    <span style={{ color: "#f3c58b" }}>{a}</span>
    <span className="muted">→ {b}</span>
  </>
);

function LiveFeed() {
  const { data } = useApi("/ingest/recent", { refresh: 8000 });
  return (
    <Card className="span-6" title={<span className="row" style={{ gap: 8 }}><span className="dot" /> Live state event stream</span>} hint="Latest records normalized by the pipeline (Zerobus push, Auto Loader file pull, Delta Sharing change feed): raw state code → canonical status">
      {!data ? (
        <Loading h={300} />
      ) : (
        <div className="feed">
          {data.events.map((e) => (
            <div key={e.event_id} className="feed-row">
              <span className="mono dim">{time(e.ingested_at)}</span>
              <StateChip code={e.state_code} />
              <span className="raw" title={e.agency}>{e.raw_status}</span>
              <span className="dim">→</span>
              <span className="row" style={{ gap: 8, minWidth: 0 }}>
                <StatusTag status={e.canonical_status} />
                {e.ingest_channel === "file_drop" && <span className="channel-tag" title={e.source_file}>Auto Loader</span>}
                {e.ingest_channel === "delta_share" && <span className="channel-tag share" title={e.source_file}>Delta Share</span>}
                <span className="dim" style={{ fontSize: 11.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.claim_id}</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

function TopCases({ cases = [] }) {
  return (
    <Card className="span-6 flush" title={<span style={{ padding: "18px 18px 0", display: "block" }}>Highest-risk claimants</span>}>
      <table>
        <thead>
          <tr>
            <th>Claimant</th>
            <th>States</th>
            <th>Signals</th>
            <th>Risk</th>
            <th className="t-right">At risk</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => (
            <tr key={c.applicant_key} className="click" onClick={() => go(`/cases/${c.applicant_key}`)}>
              <td>
                <div style={{ fontWeight: 600 }}>{c.name}</div>
                <div className="dim" style={{ fontSize: 11.5 }}>{c.top_finding}</div>
              </td>
              <td><div className="row" style={{ gap: 4 }}>{c.states.map((s) => <StateChip key={s} code={s} />)}</div></td>
              <td><TechDots rules={c.rule_hits > 0} ml={c.ml_flag} agent={!!c.agent_verdict} /></td>
              <td><RiskBar value={c.risk_score} width={70} /></td>
              <td className="t-right num" style={{ color: CATEGORY_COLORS.fraud, fontWeight: 700 }}>{money(c.at_risk)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function Skeleton() {
  return (
    <>
      <div className="skeleton" style={{ height: 70, marginBottom: 20 }} />
      <div className="kpis">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="skeleton" style={{ height: 96 }} />)}</div>
      <div className="grid g-12">
        <div className="skeleton span-8" style={{ height: 520 }} />
        <div className="skeleton span-4" style={{ height: 520 }} />
      </div>
    </>
  );
}
