import Applicant from "./pages/Applicant.jsx";
import Architecture from "./pages/Architecture.jsx";
import Cases from "./pages/Cases.jsx";
import Command from "./pages/Command.jsx";
import Detection from "./pages/Detection.jsx";
import Governance from "./pages/Governance.jsx";
import RuleStudio from "./pages/RuleStudio.jsx";
import Settings from "./pages/Settings.jsx";
import { getPersona, setPersona, useApi, useRoute } from "./lib.js";

const ICON = {
  home: <path d="M3 12l9-8 9 8M5 10v10h14V10" />,
  queue: <path d="M4 6h16M4 12h16M4 18h10" />,
  shield: <path d="M12 3l8 4v6c0 4-3.5 7-8 8-4.5-1-8-4-8-8V7z" />,
  spark: <path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6" />,
  arch: <path d="M4 5h6v5H4zM14 5h6v5h-6zM9 15h6v5H9zM7 10v3h10v-3M12 13v2" />,
  lock: <path d="M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 017 0v3" />,
  gear: <path d="M12 8a4 4 0 100 8 4 4 0 000-8zM3 12h2M19 12h2M12 3v2M12 19v2" />,
};

const NAV = [
  ["Investigations", [["/", "Command center", "home"], ["/cases", "Case queue", "queue"]]],
  ["Detection", [["/detection", "Detection models", "shield"], ["/rules", "Rule studio", "spark"]]],
  ["Platform", [["/architecture", "Architecture", "arch"], ["/governance", "Access & governance", "lock"], ["/settings", "Settings", "gear"]]],
];

function PersonaSwitch({ personas }) {
  const current = getPersona();
  const p = personas.find((x) => x.id === current) || personas[0];
  if (!p) return null;
  return (
    <div className={`persona ${current !== "investigator" ? "restricted" : ""}`}>
      <div className="eyebrow">Viewing as</div>
      <select value={current} onChange={(e) => setPersona(e.target.value)}>
        {personas.map((x) => (
          <option key={x.id} value={x.id} disabled={!x.available}>{x.label}</option>
        ))}
      </select>
      <div className="persona-role">{p.role}</div>
    </div>
  );
}

function PersonaBanner({ personas }) {
  const current = getPersona();
  const p = personas.find((x) => x.id === current);
  if (!p || current === "investigator") return null;
  return (
    <div className="persona-banner">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">{ICON.lock}</svg>
      <span>
        Viewing as <b>{p.label}</b> ({p.identity}). Unity Catalog ABAC policies enforce <b>{p.role}</b> on every query; the app adds no filtering of its own.
      </span>
      <a href="#/governance">See policies</a>
      <button className="btn sm" onClick={() => setPersona("investigator")}>Reset</button>
    </div>
  );
}

export default function App() {
  const route = useRoute();
  const health = useApi("/health", { refresh: 60000 });
  const personas = useApi("/personas");
  const h = health.data || {};
  const plist = personas.data?.personas || [];
  let page;
  if (route.startsWith("/cases/")) page = <Applicant id={route.split("/")[2]} />;
  else if (route.startsWith("/cases")) page = <Cases key={window.location.hash} />;
  else if (route.startsWith("/detection")) page = <Detection />;
  else if (route.startsWith("/rules")) page = <RuleStudio />;
  else if (route.startsWith("/architecture")) page = <Architecture />;
  else if (route.startsWith("/governance")) page = <Governance />;
  else if (route.startsWith("/settings")) page = <Settings />;
  else page = <Command />;
  const active = (p) => (p === "/" ? route === "/" : route.startsWith(p));

  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">
          <div className="brand-mark">
            <svg width="22" height="22" viewBox="0 0 32 32"><path d="M6 24 L16 6 L26 24 Z" fill="none" stroke="#22d3ee" strokeWidth="2.5" strokeLinejoin="round" /><circle cx="16" cy="19" r="3" fill="#ff4d6d" /></svg>
          </div>
          <div>
            <div className="brand-title">UI Integrity</div>
            <div className="brand-sub">{h.agency_banner || "U.S. Dept. of Labor · ETA"}</div>
          </div>
        </div>
        <PersonaSwitch personas={plist} />
        <nav className="nav">
          {NAV.map(([group, items]) => (
            <div key={group} className="nav-group">
              <div className="nav-label">{group}</div>
              {items.map(([p, label, icon]) => (
                <a key={p} href={`#${p}`} className={active(p) ? "active" : ""}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{ICON[icon]}</svg>
                  {label}
                </a>
              ))}
            </div>
          ))}
        </nav>
        <div className="side-foot">
          <div className="stack-row"><span className={`dot ${h.warehouse ? "" : "off"}`} />Unity Catalog · {h.catalog || "lanl"}.{h.schema || "dol_ui"}</div>
          <div className="stack-row"><span className={`dot ${h.lakebase ? "" : "off"}`} />Lakebase · {h.lakebase_branch || "production"}</div>
          <div className="stack-row"><span className={`dot ${h.genie_agent_id ? "" : "off"}`} />Genie Agent mode</div>
          <div className="dim" style={{ marginTop: 6 }}>Synthetic data for demonstration only</div>
        </div>
      </aside>
      <main className="main">
        <PersonaBanner personas={plist} />
        {page}
      </main>
    </div>
  );
}
