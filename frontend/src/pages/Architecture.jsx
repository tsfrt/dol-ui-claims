import { useState } from "react";
import { Card, Loading } from "../components/ui.jsx";
import { TECH_COLORS, ago, api, go, num, pct, useApi } from "../lib.js";

const C = { source: "#94a3b8", ingest: "#fbbf24", sdp: "#34d399", detect: "#f472b6", serve: "#60a5fa" };

const APIS = [
  ["Zerobus Ingest REST", "State producers write records straight into a Unity Catalog Delta table, no message bus to run"],
  ["Auto Loader", "Incrementally discovers new state batch files in a Unity Catalog volume, exactly once"],
  ["Delta Sharing", "States already on Databricks grant DOL a share of their own table; DOL streams its change feed with no copy job"],
  ["Statement Execution API", "Every number in this app is a governed SQL query on serverless SQL, run as the selected persona's identity"],
  ["Foundation Model API", "Rule studio drafts SQL from plain English, grounded in Unity Catalog metadata"],
  ["Genie Agents API", "Agent mode investigates a claimant across claims, intel and identity links and returns a narrative"],
  ["Lakebase Postgres API", "Analyst inputs, app config and analyst rules; a database branch per pull request"],
  ["Unity Catalog Policies API", "Attribute-based row filters and column masks keyed off governed tags"],
  ["Jobs API", "Orchestrates seed, stream, pipeline, governance, scoring and agent review"],
];

function ext(href) {
  return href ? { href, target: "_blank", rel: "noreferrer" } : {};
}

function Node({ title, sub, value, unit, href, onClick, color, children, status }) {
  const Tag = href || onClick ? "a" : "div";
  return (
    <Tag className={`arch-node ${href || onClick ? "link" : ""}`} style={{ "--c": color }} {...ext(href)} onClick={onClick}>
      <div className="arch-node-head">
        <span className="arch-node-title">{title}</span>
        {status}
        {(href || onClick) && <span className="arch-open">{href ? "↗" : "→"}</span>}
      </div>
      {value != null && (
        <div className="arch-metric">
          {value}
          {unit && <span>{unit}</span>}
        </div>
      )}
      {sub && <div className="arch-sub">{sub}</div>}
      {children}
    </Tag>
  );
}

function Lane({ label, color, href, action, children }) {
  return (
    <div className="arch-lane">
      {href ? (
        <a className="arch-lane-label link" style={{ color }} {...ext(href)}>{label} ↗</a>
      ) : (
        <div className="arch-lane-label" style={{ color }}>{label}</div>
      )}
      <div className="arch-lane-body">
        {action}
        {children}
      </div>
    </div>
  );
}

const Flow = () => (
  <div className="arch-flow" aria-hidden>
    <span />
    <span />
    <span />
  </div>
);

function RunState({ run }) {
  if (!run) return <span className="badge">No runs yet</span>;
  const s = run.result || run.life_cycle;
  const tone = s === "SUCCESS" ? "clean" : ["RUNNING", "PENDING", "QUEUED"].includes(s) ? "agent" : s ? "fraud" : "";
  return <span className={`badge ${tone}`}>{(s || "unknown").toLowerCase()}</span>;
}

function PipelineState({ p }) {
  const s = p?.last_update?.state;
  if (!s) return null;
  return <span className={`badge ${s === "COMPLETED" ? "clean" : s === "FAILED" ? "fraud" : "agent"}`}>{s.toLowerCase()}</span>;
}

export default function Architecture() {
  const { data, error, reload } = useApi("/platform", { refresh: 20000 });
  const [run, setRun] = useState(null);

  if (error) return <div className="empty">Could not load platform status: {error.message}</div>;
  if (!data) return <Loading h={600} />;
  const s = data.stats || {};
  const L = data.links;
  const intelRows = data.intel.reduce((a, r) => a + Number(r.n || 0), 0);
  const filesPending = Math.max(0, (s.file_batches || 0) - (data.files ? data.files.length : s.files_loaded || 0));
  const fed = data.federation;
  const PUSH_STATES = data.transports.zerobus || [];
  const shares = data.shares || [];
  const staged = shares.some((x) => !x.mounted);
  const sharePending = Math.max(0, (s.share_outbox || 0) - (s.share_events || 0));

  async function trigger() {
    setRun({ busy: true });
    try {
      const r = await api("/platform/stream", { method: "POST" });
      setRun(r);
      setTimeout(reload, 3000);
    } catch (e) {
      setRun({ error: e.message });
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Platform · system architecture</div>
          <h1>One governed platform from state system to investigator</h1>
          <div className="sub">
            Every box is a live object in this Databricks workspace. Counts are queried from Unity Catalog as you look at them; click any box to open the
            pipeline, table, model, agent or database behind it. Everything is serverless and deployed from a single Declarative Automation Bundle.
          </div>
        </div>
        <div className="row" style={{ gap: 8 }}>
          <a className="badge" {...ext(L.schema)}>Unity Catalog · {data.catalog} ↗</a>
          <a className="badge" {...ext(L.lineage)}>Lineage ↗</a>
        </div>
      </div>

      <Card className="arch-card">
        <div className="arch">
          <Lane label="State & federal sources" color={C.source}>
            <Node title="State UI systems · push" color={C.source} value={PUSH_STATES.length} unit="agencies" sub="Each agency's own JSON contract, codes and date formats">
              <div className="arch-chips">{PUSH_STATES.map((c) => <span key={c} className="state-chip">{c}</span>)}</div>
            </Node>
            <Node title="Michigan UIA · MiWAM batch" color={C.source} value={s.file_batches} unit="weekly files" sub="Fixed-layout CSV extract published to a drop zone, the way many legacy systems deliver">
              <div className="arch-chips"><span className="state-chip">MI</span>{filesPending > 0 && <span className="channel-tag">{filesPending} not yet delivered</span>}</div>
            </Node>
            <Node title="States on Databricks · Delta Sharing" color={C.source} value={shares.length} unit="agencies"
              status={<span className={`badge ${staged ? "eligibility" : "clean"}`}>{staged ? "staged" : "live share"}</span>}
              sub="Typed claim status logs kept in each state's own lakehouse; one targeted share per state, granted only to DOL, with history">
              <div className="arch-chips">
                {shares.map((x) => <a key={x.state_code} className="state-chip" title={`${x.share} → ${x.source}`} {...ext(x.url)}>{x.state_code}</a>)}
                {sharePending > 0 && <span className="channel-tag">{num(sharePending)} changes not yet committed</span>}
              </div>
            </Node>
            <Node title="Federal intel" color={C.source} value={num(intelRows)} unit="records" sub={data.intel.map((r) => r.name).join(" · ")} href={L.schema} />
            {fed && (
              <Node title="Michigan UI tax wages · federated" color={C.source} value={num(fed.wage_rows)} unit="rows in place" sub="Postgres system of record queried through Lakehouse Federation, never copied" />
            )}
          </Lane>
          <Flow />
          <Lane label="Ingest" color={C.ingest}>
            <Node title="Zerobus Ingest" color={C.ingest} value={num(s.zerobus_landed)} unit="records landed" href={L.landing}
              sub={<>Direct-write REST into <code>bronze_claim_events</code>{s.last_zerobus_write && <> · last write {ago(s.last_zerobus_write)}</>}{s.zerobus_outbox > s.zerobus_landed && <> · {num(s.zerobus_outbox - s.zerobus_landed)} still in state outboxes</>}</>} />
            <Node title="Auto Loader" color={C.ingest} value={data.files ? data.files.length : num(s.files_loaded)} unit="files picked up" href={L.volume}
              sub={<>Watches <code>/Volumes/{data.catalog.replace(".", "/")}/state_drops/mi</code> and loads each new file exactly once</>} />
            <Node title="Delta Sharing" color={C.ingest} value={num(s.share_events)} unit="changes read" href={shares[0]?.url}
              sub={<>Streams each share's change feed ({num(s.share_versions)} table versions so far); nothing to run on the state side, and each state can revoke access{staged && <> · <b>staged:</b> reading stand-in tables in this metastore until the shares are mounted</>}</>} />
          </Lane>
          <Flow />
          <Lane label="Lakeflow Spark Declarative Pipeline" color={C.sdp} href={data.pipeline?.url}
            action={data.pipeline?.url && (
              <a className="arch-pipeline" {...ext(data.pipeline.url)}>
                <span>Open pipeline</span>
                <PipelineState p={data.pipeline} />
                {data.pipeline.last_update?.at && <span className="dim">{ago(data.pipeline.last_update.at)}</span>}
                <span className="arch-open">↗</span>
              </a>
            )}>
            <Node title="Bronze event stream" color={C.sdp} value={num(s.bronze_rows)} unit="rows" href={L.bronze} sub="Three kinds of append flow (push, file pull, share change feed) into one streaming table" />
            <Node title="Silver canonical events" color={C.sdp} value={num(s.events)} unit="events" href={L.silver} sub={`${s.states} state contracts parsed into one model · data quality expectations drop malformed records`} />
            <Node title="Claim history · Auto CDC" color={C.sdp} value={num(s.history_rows)} unit="SCD2 rows" sub="Out-of-order status events resolved into a full claim timeline" />
            <Node title="Gold analytical products" color={C.sdp} value={num(s.claimants)} unit="claimants" href={L.gold} sub={`${num(s.claims)} claims · ${num(s.claim_weeks)} benefit weeks · cross-state identity resolution`} />
          </Lane>
          <Flow />
          <Lane label="Detection" color={C.detect}>
            <Node title="Python rules" color={TECH_COLORS.rules} value={num(s.rule_findings)} unit="findings" href={L.findings} sub={`${s.rules_firing} rules cross-matching claims against federal intel, inside the pipeline`} />
            <Node title="Analyst rules · Rule studio" color={TECH_COLORS.rules} value={num(s.custom_findings)} unit="findings" onClick={() => go("/rules")}
              sub={`${s.custom_rules || 0} promoted from plain English · drafted by ${data.rule_author}`} />
            <Node title="ML model" color={TECH_COLORS.ml} value={data.model.auc != null ? Number(data.model.auc).toFixed(3) : "—"} unit="ROC AUC" href={data.model.url}
              sub={`${data.model.name.split(".").pop()} v${data.model.version || "?"} · precision ${pct(data.model.precision, 0)} · recall ${pct(data.model.recall, 0)} · MLflow tracked`} />
            <Node title="Genie Agent mode" color={TECH_COLORS.agent} value={num(s.agent_findings)} unit="reviews" href={L.agent} sub="Multi-step investigations over the same governed tables" />
          </Lane>
          <Flow />
          <Lane label="Serve & govern" color={C.serve}>
            <Node title="Databricks App" color={C.serve} href={L.app} sub="This workbench: React + FastAPI; every query runs as the selected persona's service principal" />
            <Node title="Lakebase Postgres" color={C.serve} value={data.branches.length || "—"} unit={data.branches.length === 1 ? "branch" : "branches"} href={L.lakebase}
              sub="Dispositions, notes, config and analyst rules; Prisma migrations">
              <div className="arch-chips">{data.branches.map((b) => <span key={b.name} className={`branch-chip ${b.default ? "default" : ""}`}>{b.name}</span>)}</div>
            </Node>
            <Node title="Unity Catalog governance" color={C.serve} value={data.policies} unit="ABAC policies" onClick={() => go("/governance")}
              sub={`${data.governance.tagged_columns} governed column tags across ${data.governance.tagged_tables} tables · ${data.governance.principals} entitled principals`} />
          </Lane>
        </div>
      </Card>

      <div className="grid g-12 mt">
        <Card className="span-4" title="Orchestration" hint="Lakeflow Jobs, defined in the bundle">
          {[["orchestrate", "Rebuild demo", "Seed → stream + file drop + share commits → full pipeline refresh → governance → analyst rules → ML → Genie review"],
            ["stream", "Stream and score", "Deliver new Zerobus events, Michigan files and shared state commits → incremental refresh → rescore"]].map(([k, label, desc]) => {
            const j = data[k];
            return (
              <div key={k} className="arch-job">
                <div className="between">
                  <a className="arch-job-name" {...ext(j.url)}>{label} ↗</a>
                  <RunState run={j.last_run} />
                </div>
                <div className="arch-sub">{desc}</div>
                {j.last_run?.started && <div className="dim" style={{ fontSize: 11.5 }}>Last run {ago(j.last_run.started)}{j.last_run.url && <> · <a {...ext(j.last_run.url)}>run details ↗</a></>}</div>}
              </div>
            );
          })}
          <button className="btn primary" onClick={trigger} disabled={run?.busy} style={{ marginTop: 6 }}>
            {run?.busy ? "Starting…" : "Run a micro-batch now"}
          </button>
          {run?.run_id && <div className="arch-sub" style={{ marginTop: 8 }}>Started run <a {...ext(run.url)}>{run.run_id} ↗</a>. New events appear in the command center as the pipeline finishes.</div>}
          {run?.error && <div style={{ marginTop: 8, color: "var(--fraud)", fontSize: 12.5 }}>{run.error}</div>}
        </Card>

        <Card className="span-4" title="CI/CD" hint="GitHub Actions + Declarative Automation Bundles">
          <ol className="arch-steps">
            <li><b>Feature branch PR</b> deploys a preview app <code>dol-ui-claims-&lt;branch&gt;</code> with its own <b>Lakebase branch</b> forked from production; Prisma migrations run against the branch.</li>
            <li><b>Approved review required</b>: main is protected and only accepts PRs that pass the preview check.</li>
            <li><b>Merge or close</b> destroys the preview app and deletes its database branch.</li>
            <li><b>Tag on main</b> (<code>v*</code>) runs <code>prisma migrate deploy</code> on production and <code>bundle deploy -t prod</code>.</li>
          </ol>
          <div className="arch-targets">
            <span className="branch-chip">dev · per-developer</span>
            <span className="branch-chip">preview · per PR</span>
            <span className="branch-chip default">prod · tagged releases</span>
          </div>
        </Card>

        <Card className="span-4" title="Security posture" hint="Controls that carry over to FedRAMP Moderate workspaces">
          <ul className="arch-list">
            <li>All compute serverless: SQL warehouse, pipeline, jobs, app and Lakebase</li>
            <li>PII masked and state-scoped by <b>Unity Catalog ABAC</b>, enforced on every engine including this app and Genie</li>
            <li>Service principals per producer, app and persona; OAuth M2M tokens scoped down to a single table for Zerobus</li>
            <li>Secrets in a Databricks secret scope, injected as app resources</li>
            <li>Full lineage and audit from state record to disposition</li>
          </ul>
        </Card>

        <Card className="span-12" title="Detection source code" hint="Open the code that produced every finding, in this workspace"
          right={data.github && <a className="badge" {...ext(data.github)}>GitHub repository ↗</a>}>
          <div className="arch-apis">
            {Object.entries(data.code || {}).map(([k, c]) => (
              <a key={k} className="arch-api arch-code" {...ext(c.url)}>
                <div className="arch-api-name">{"</>"} {c.label} {c.url && <span className="arch-open">↗</span>}</div>
                <div className="arch-sub">{c.description}</div>
                <div className="arch-path">{c.path}{c.github && c.url !== c.github && <> · <span onClick={(e) => { e.preventDefault(); window.open(c.github, "_blank", "noreferrer"); }} className="arch-gh">GitHub</span></>}</div>
              </a>
            ))}
          </div>
        </Card>

        <Card className="span-12" title="Platform APIs behind the demo" hint="Everything shown is reachable programmatically">
          <div className="arch-apis">
            {APIS.map(([n, d]) => (
              <div key={n} className="arch-api">
                <div className="arch-api-name">{n}</div>
                <div className="arch-sub">{d}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </>
  );
}
