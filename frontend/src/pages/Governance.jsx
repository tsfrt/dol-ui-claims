import { useEffect, useState } from "react";
import { Card, Loading, Switch } from "../components/ui.jsx";
import { api, getPersona, moneyShort, num, useApi } from "../lib.js";

const ALL_STATES = ["CA", "CO", "FL", "GA", "IL", "MA", "MI", "NC", "NJ", "NY", "OH", "PA", "TX", "WA"];
const isMasked = (v) => v == null || String(v).includes("•");

function Field({ label, value }) {
  const masked = isMasked(value);
  return (
    <div className={`gov-field ${masked ? "masked" : ""}`}>
      <span>{label}</span>
      <b className="mono">{value ?? "NULL"}</b>
    </div>
  );
}

function ViewCard({ v, you }) {
  const states = v.states || [];
  return (
    <div className={`card gov-view ${you ? "you" : ""}`}>
      <div className="between">
        <div>
          <div className="gov-view-title">{v.label}</div>
          <div className="dim mono" style={{ fontSize: 11 }}>{v.identity}</div>
        </div>
        {you && <span className="badge agent">you</span>}
      </div>
      {v.error ? (
        <div className="empty">{v.error}</div>
      ) : (
        <>
          <div className="gov-stats">
            <div><div className="kpi-value">{num(v.claims)}</div><div className="dim">claims visible</div></div>
            <div><div className="kpi-value">{moneyShort(v.total_paid)}</div><div className="dim">benefits visible</div></div>
          </div>
          <div className="gov-states">
            {ALL_STATES.filter((s) => s !== "MI" || states.includes("MI")).map((s) => (
              <span key={s} className={`state-chip ${states.includes(s) ? "" : "off"}`}>{s}</span>
            ))}
          </div>
          <div className="dim" style={{ fontSize: 11, margin: "12px 0 6px" }}>Same claimant record, as returned by Unity Catalog</div>
          <Field label="Name" value={v.sample_name} />
          <Field label="Date of birth" value={v.sample_dob} />
          <Field label="SSN last 4" value={v.sample_ssn4} />
        </>
      )}
      <div className="dim mono" style={{ fontSize: 10.5, marginTop: 10 }}>current_user() = {v.principal || "—"}</div>
    </div>
  );
}

function EntitlementRow({ e, canEdit, onSaved }) {
  const [scope, setScope] = useState(e.state_scope || []);
  const [pii, setPii] = useState(!!e.pii_cleared);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setScope(e.state_scope || []);
    setPii(!!e.pii_cleared);
  }, [e]);
  const all = scope.includes("*");
  const dirty = JSON.stringify([...scope].sort()) !== JSON.stringify([...(e.state_scope || [])].sort()) || pii !== !!e.pii_cleared;
  const editable = e.editable && canEdit;
  const toggle = (s) => {
    if (s === "*") return setScope(all ? ["CA"] : ["*"]);
    const base = scope.filter((x) => x !== "*");
    const next = base.includes(s) ? base.filter((x) => x !== s) : [...base, s];
    setScope(next.length ? next : base);
  };
  async function save() {
    setBusy(true);
    try {
      await api(`/governance/entitlements/${encodeURIComponent(e.principal)}`, { method: "PUT", body: { state_scope: scope, pii_cleared: pii } });
      onSaved();
    } finally {
      setBusy(false);
    }
  }
  return (
    <tr>
      <td>
        <div style={{ fontWeight: 600 }}>{e.display_name}</div>
        <div className="dim mono" style={{ fontSize: 11 }}>{e.principal}</div>
      </td>
      <td><span className="badge">{e.role}</span></td>
      <td>
        <div className="gov-states" style={{ margin: 0 }}>
          <button className={`state-chip toggle ${all ? "" : "off"}`} disabled={!editable} onClick={() => toggle("*")}>All</button>
          {!all && ALL_STATES.map((s) => (
            <button key={s} className={`state-chip toggle ${scope.includes(s) ? "" : "off"}`} disabled={!editable} onClick={() => toggle(s)}>{s}</button>
          ))}
        </div>
      </td>
      <td><Switch on={pii} disabled={!editable} onChange={setPii} /></td>
      <td className="t-right">{editable && <button className="btn sm primary" disabled={!dirty || busy} onClick={save}>{busy ? "Saving…" : "Apply"}</button>}</td>
    </tr>
  );
}

export default function Governance() {
  const { data, loading, reload } = useApi("/governance");
  if (loading && !data) return <Loading h={600} />;
  if (!data) return <div className="empty">Governance metadata unavailable</div>;
  const you = getPersona();
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Access & governance</div>
          <h1>One copy of the data. Every identity sees only what it is entitled to.</h1>
          <div className="sub">
            Columns carry governed tags. Schema-level ABAC policies in Unity Catalog mask PII and filter rows by owning state for every table that has those tags, including tables
            created tomorrow. The same queries below run under three different identities; nothing is filtered by the app.
          </div>
        </div>
        <a className="btn" href={data.catalog_url} target="_blank" rel="noreferrer">Open in Catalog Explorer ↗</a>
      </div>

      <div className="grid g-12">
        {data.views.map((v) => (
          <div key={v.persona} className="span-4"><ViewCard v={v} you={v.persona === you} /></div>
        ))}

        <Card className="span-7" title="ABAC policies on lanl.dol_ui" hint="Defined once at the schema; applied to every matching column">
          <div className="gov-policies">
            {data.policies.map((p) => (
              <div key={p.name} className="gov-policy">
                <div className="between">
                  <span className="mono" style={{ fontWeight: 600, color: "var(--text)" }}>{p.name}</span>
                  <span className={`badge ${p.type === "row_filter" ? "rules" : "ml"}`}>{p.type === "row_filter" ? "Row filter" : "Column mask"}</span>
                </div>
                <div className="muted" style={{ fontSize: 12.5, margin: "4px 0 6px" }}>{p.comment}</div>
                <div className="mono dim" style={{ fontSize: 11 }}>MATCH {p.match} → {p.function} · TO {p.to.join(", ")}</div>
              </div>
            ))}
          </div>
        </Card>

        <Card className="span-5" title="Governed tags" hint="System data classes plus governed tags for ownership">
          <div className="gov-tags">
            {data.tags.map((t) => (
              <div key={t.tag} className="gov-tag">
                <div className="between">
                  <span className="badge">{t.tag}</span>
                  <span className="dim">{t.columns.length} columns</span>
                </div>
                <div className="dim mono" style={{ fontSize: 10.5, marginTop: 5 }}>{t.columns.slice(0, 6).join(" · ")}{t.columns.length > 6 ? " …" : ""}</div>
              </div>
            ))}
          </div>
        </Card>

        <Card
          className="span-12"
          title="Entitlements registry"
          hint="ref_data_entitlements · read by every policy function through current_user(), so changes apply on the next query with no regrants or group sync"
        >
          <table>
            <thead><tr><th>Principal</th><th>Role</th><th>State scope</th><th>PII cleared</th><th /></tr></thead>
            <tbody>
              {data.entitlements.map((e) => <EntitlementRow key={e.principal} e={e} canEdit={data.can_edit} onSaved={reload} />)}
            </tbody>
          </table>
        </Card>
      </div>
    </>
  );
}
