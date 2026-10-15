import { useMemo, useState } from "react";
import { Card, CategoryBadge, Loading, RiskBar, StateChip, StatusTag, TechDots, Verdict } from "../components/ui.jsx";
import { CATEGORY_COLORS, go, money, num, useApi } from "../lib.js";

const STATES = ["CA", "TX", "NY", "FL", "PA", "IL", "WA", "MA", "GA", "NJ", "MI", "OH", "CO", "NC"];

function initial() {
  const q = new URLSearchParams(window.location.hash.split("?")[1] || "");
  return { state: q.get("state") || "", category: q.get("category") || "", technique: q.get("technique") || "" };
}

export default function Cases() {
  const [f, setF] = useState(initial);
  const [search, setSearch] = useState("");
  const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString();
  const { data, loading } = useApi(`/cases?${qs}`, { deps: [qs] });
  const rows = useMemo(() => {
    const s = search.trim().toLowerCase();
    return (data?.cases || []).filter((c) => !s || c.name.toLowerCase().includes(s) || c.applicant_key.startsWith(s) || (c.ssn_last4 || "").includes(s));
  }, [data, search]);
  const set = (k, v) => setF((p) => ({ ...p, [k]: p[k] === v ? "" : v }));
  const totals = data?.totals;

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Case Queue</div>
          <h1>Flagged claimants</h1>
          <div className="sub">Every claimant flagged by at least one technique, ranked by combined risk. Claims from all states are resolved into a single cross-state identity.</div>
        </div>
        {totals && (
          <div className="row" style={{ gap: 18 }}>
            <Stat label="Claimants" value={num(totals.claimants)} />
            <Stat label="At risk" value={money(totals.at_risk)} color={CATEGORY_COLORS.fraud} />
          </div>
        )}
      </div>

      <Card>
        <div className="row wrap" style={{ gap: 12 }}>
          <input placeholder="Search name, SSN last 4, or key" value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 260 }} />
          <div className="seg">
            {["fraud", "eligibility"].map((c) => (
              <button key={c} className={f.category === c ? "on" : ""} onClick={() => set("category", c)}>{c === "fraud" ? "Fraud" : "Eligibility"}</button>
            ))}
          </div>
          <div className="seg">
            {[["rules", "Rules"], ["ml", "ML"], ["agent", "Genie"], ["ml_only", "ML only"]].map(([k, l]) => (
              <button key={k} className={f.technique === k ? "on" : ""} onClick={() => set("technique", k)}>{l}</button>
            ))}
          </div>
          <div className="seg">
            {STATES.map((s) => (
              <button key={s} className={f.state === s ? "on" : ""} onClick={() => set("state", s)} style={{ fontFamily: "var(--mono)", padding: "7px 9px" }}>{s}</button>
            ))}
          </div>
        </div>
      </Card>

      <Card className="flush mt">
        {loading && !data ? (
          <div style={{ padding: 18 }}><Loading h={400} /></div>
        ) : (
          <div className="scroll-x">
            <table>
              <thead>
                <tr>
                  <th>Risk</th>
                  <th>Claimant</th>
                  <th>States</th>
                  <th>Findings</th>
                  <th>Techniques</th>
                  <th>ML score</th>
                  <th>Genie verdict</th>
                  <th>Status</th>
                  <th className="t-right">Paid</th>
                  <th className="t-right">At risk</th>
                  <th>Case</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.applicant_key} className="click" onClick={() => go(`/cases/${c.applicant_key}`)}>
                    <td><RiskBar value={c.risk_score} width={64} /></td>
                    <td>
                      <div style={{ fontWeight: 600 }}>{c.name}</div>
                      <div className="dim mono">•••-••-{c.ssn_last4}</div>
                    </td>
                    <td><div className="row" style={{ gap: 4 }}>{c.states.map((s) => <StateChip key={s} code={s} />)}</div></td>
                    <td style={{ maxWidth: 300 }}>
                      <div className="row wrap" style={{ gap: 4 }}>
                        {c.categories.map((cat) => <CategoryBadge key={cat} category={cat} />)}
                        <span className="muted" style={{ fontSize: 12 }}>{c.findings.slice(0, 2).join(", ")}{c.findings.length > 2 ? ` +${c.findings.length - 2}` : ""}</span>
                      </div>
                    </td>
                    <td><TechDots rules={c.rule_hits > 0} ml={c.ml_flag} agent={!!c.agent_verdict} /></td>
                    <td className="num mono" style={{ color: c.ml_flag ? "#a78bfa" : "var(--muted)", fontWeight: 700 }}>{Math.round((c.ml_score || 0) * 100)}</td>
                    <td>{c.agent_verdict ? <Verdict verdict={c.agent_verdict} /> : <span className="dim">—</span>}</td>
                    <td><StatusTag status={c.latest_status} /></td>
                    <td className="t-right num">{money(c.total_paid)}</td>
                    <td className="t-right num" style={{ color: CATEGORY_COLORS.fraud, fontWeight: 700 }}>{money(c.at_risk)}</td>
                    <td><span className={`badge ${c.case_status === "closed" ? "clean" : c.case_status === "in_review" ? "agent" : ""}`}>{(c.case_status || "new").replace("_", " ")}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!rows.length && <div className="empty">No claimants match these filters</div>}
          </div>
        )}
      </Card>
    </>
  );
}

const Stat = ({ label, value, color }) => (
  <div style={{ textAlign: "right" }}>
    <div className="kpi-label">{label}</div>
    <div className="num" style={{ fontSize: 22, fontWeight: 800, color }}>{value}</div>
  </div>
);
