import { useEffect, useState } from "react";
import { Card, Loading } from "../components/ui.jsx";
import { api, useApi } from "../lib.js";

const FIELDS = [
  ["genie_agent_id", "Genie agent ID", "Agent used for Agent mode investigations"],
  ["ml_flag_threshold", "ML flag threshold", "Score at or above which the ML model flags a claimant (0–1). Blank uses the model's F1-optimal threshold."],
  ["queue_limit", "Case queue size", "Maximum claimants loaded into the queue"],
  ["agency_banner", "Agency banner", "Text shown in the app header"],
];

export default function Settings() {
  const { data, loading, reload } = useApi("/config");
  const health = useApi("/health");
  const [form, setForm] = useState({});
  const [saved, setSaved] = useState(null);
  useEffect(() => data && setForm(data.config || {}), [data]);

  async function save() {
    await api("/config", { method: "PUT", body: form });
    setSaved("Saved to Lakebase");
    reload();
    setTimeout(() => setSaved(null), 2500);
  }

  if (loading && !data) return <Loading h={400} />;
  const h = health.data || {};
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Settings</div>
          <h1>App configuration</h1>
          <div className="sub">Configuration and analyst inputs live in Lakebase Postgres. Feature branches get their own Lakebase branch so preview apps never touch production data.</div>
        </div>
      </div>
      <div className="grid g-12">
        <Card className="span-7" title="Configuration" hint="app_config table · Lakebase">
          <div className="grid" style={{ gap: 14 }}>
            {FIELDS.map(([k, label, help]) => (
              <label key={k} className="field">
                {label}
                <input value={form[k] ?? ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
                <span className="dim" style={{ fontWeight: 400 }}>{help}</span>
              </label>
            ))}
          </div>
          <div className="row mt" style={{ gap: 10 }}>
            <button className="btn primary" onClick={save}>Save</button>
            {saved && <span className="badge clean">{saved}</span>}
          </div>
        </Card>
        <Card className="span-5" title="Platform" hint="Live connections used by this app">
          <dl className="kv">
            <dt>Lakebase</dt><dd>{h.lakebase ? <span className="badge clean">connected</span> : <span className="badge fraud">unavailable</span>} <span className="dim mono">{h.lakebase_endpoint}</span></dd>
            <dt>SQL warehouse</dt><dd>{h.warehouse ? <span className="badge clean">connected</span> : <span className="badge fraud">unavailable</span>} <span className="dim mono">{h.warehouse_id}</span></dd>
            <dt>Unity Catalog</dt><dd className="mono">{h.catalog}.{h.schema}</dd>
            <dt>Genie agent</dt><dd className="mono">{h.genie_agent_id || "not configured"}</dd>
            <dt>Ingest</dt><dd>Zerobus Ingest → <span className="mono">bronze_claim_events</span> · Auto Loader → <span className="mono">state_drops</span> volume · Delta Sharing change feeds</dd>
            <dt>Pipeline</dt><dd>Lakeflow Spark Declarative Pipelines</dd>
          </dl>
        </Card>
      </div>
    </>
  );
}
