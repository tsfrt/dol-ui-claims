import { CATEGORY_COLORS, STATUS_COLORS, TECH_COLORS, VERDICT_STYLE } from "../lib.js";

export function Card({ title, hint, right, children, className = "", stripe, style }) {
  return (
    <section className={`card ${className}`} style={style}>
      {stripe && <div className="stripe" style={{ background: stripe }} />}
      {(title || right) && (
        <div className="card-head">
          <div>
            {title && <h2>{title}</h2>}
            {hint && <div className="hint">{hint}</div>}
          </div>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export function Kpi({ label, value, foot, tone }) {
  return (
    <div className={`card kpi ${tone || ""}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {foot && <div className="kpi-foot">{foot}</div>}
    </div>
  );
}

export const StateChip = ({ code }) => <span className="state-chip">{code}</span>;

export function StatusTag({ status }) {
  const c = STATUS_COLORS[status] || "#64748b";
  return (
    <span className="canon" style={{ color: c, background: `${c}1f`, border: `1px solid ${c}55` }}>
      {status || "unknown"}
    </span>
  );
}

export function CategoryBadge({ category }) {
  if (!category) return null;
  const label = category === "eligibility" ? "Eligibility" : category === "fraud" ? "Fraud" : "Clean";
  return <span className={`badge ${category}`}>{label}</span>;
}

export function TechDots({ rules, ml, agent }) {
  return (
    <span className="tech-dots" title="Rules · ML · Genie agent">
      <span className={`tech-dot rules ${rules ? "on" : ""}`}>R</span>
      <span className={`tech-dot ml ${ml ? "on" : ""}`}>M</span>
      <span className={`tech-dot agent ${agent ? "on" : ""}`}>G</span>
    </span>
  );
}

export function Verdict({ verdict, large }) {
  const s = VERDICT_STYLE[verdict] || VERDICT_STYLE.NEEDS_REVIEW;
  return (
    <span className="verdict" style={{ background: s.bg, color: s.fg, fontSize: large ? 13 : 11, border: `1px solid ${s.fg}55` }}>
      {s.label}
    </span>
  );
}

export function RiskBar({ value, width = 120 }) {
  const v = Math.max(0, Math.min(1, value || 0));
  const color = v >= 0.85 ? CATEGORY_COLORS.fraud : v >= 0.6 ? CATEGORY_COLORS.eligibility : v >= 0.3 ? "#94a3b8" : CATEGORY_COLORS.clean;
  return (
    <div className="row" style={{ gap: 8 }}>
      <div className="bar" style={{ width }}>
        <span style={{ width: `${v * 100}%`, background: `linear-gradient(90deg, ${color}88, ${color})` }} />
      </div>
      <span className="num mono" style={{ color, fontWeight: 700, minWidth: 26 }}>{Math.round(v * 100)}</span>
    </div>
  );
}

export function BarList({ items, color, format = (v) => v, max }) {
  const m = max || Math.max(1, ...items.map((i) => i.value));
  return (
    <div className="barlist">
      {items.map((i) => (
        <div className="barlist-row" key={i.key || i.label}>
          <div style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{i.label}</div>
          <div className="num muted" style={{ fontSize: 12.5 }}>{format(i.value)}{i.extra ? <span className="dim"> · {i.extra}</span> : null}</div>
          <div className="bar">
            <span style={{ width: `${(i.value / m) * 100}%`, background: i.color || color }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function Gauge({ value, size = 150, label, color }) {
  const v = Math.max(0, Math.min(1, value || 0));
  const r = size / 2 - 12;
  const c = Math.PI * r;
  const col = color || (v >= 0.85 ? CATEGORY_COLORS.fraud : v >= 0.6 ? CATEGORY_COLORS.eligibility : v >= 0.3 ? "#94a3b8" : CATEGORY_COLORS.clean);
  return (
    <svg width={size} height={size / 2 + 22} viewBox={`0 0 ${size} ${size / 2 + 22}`}>
      <defs>
        <linearGradient id={`g-${size}-${label}`} x1="0" x2="1">
          <stop offset="0" stopColor={col} stopOpacity="0.4" />
          <stop offset="1" stopColor={col} />
        </linearGradient>
      </defs>
      <path d={`M 12 ${size / 2} A ${r} ${r} 0 0 1 ${size - 12} ${size / 2}`} stroke="rgba(255,255,255,.07)" strokeWidth="12" fill="none" strokeLinecap="round" />
      <path
        d={`M 12 ${size / 2} A ${r} ${r} 0 0 1 ${size - 12} ${size / 2}`}
        stroke={`url(#g-${size}-${label})`}
        strokeWidth="12"
        fill="none"
        strokeLinecap="round"
        strokeDasharray={`${c * v} ${c}`}
        style={{ filter: `drop-shadow(0 0 8px ${col}66)`, transition: "stroke-dasharray .8s ease" }}
      />
      <text x={size / 2} y={size / 2 - 4} textAnchor="middle" fill="#e8edf9" fontSize={size / 4.4} fontWeight="800" className="num">
        {Math.round(v * 100)}
      </text>
      {label && (
        <text x={size / 2} y={size / 2 + 16} textAnchor="middle" fill="#8d9bbd" fontSize="11" letterSpacing="1">
          {label}
        </text>
      )}
    </svg>
  );
}

export function Loading({ h = 200 }) {
  return <div className="skeleton" style={{ height: h }} />;
}

export function Json({ value }) {
  const text = JSON.stringify(value, null, 2) || "";
  const html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/("(?:\\.|[^"\\])*")(\s*:)?|\b(-?\d+(?:\.\d+)?)\b/g, (m, s, colon, n) => {
      if (s) return colon ? `<span class="k">${s}</span>${colon}` : `<span class="s">${s}</span>`;
      return `<span class="n">${n}</span>`;
    });
  return <pre className="json" dangerouslySetInnerHTML={{ __html: html }} />;
}

export function Switch({ on, onChange, disabled }) {
  return <button className={`switch ${on ? "on" : ""}`} disabled={disabled} onClick={() => onChange(!on)} aria-pressed={on} style={{ border: undefined }} />;
}

export const TechLabel = { rules: "Rules engine", ml: "ML model", agent: "Genie agent" };
export const techColor = (t) => TECH_COLORS[t];
