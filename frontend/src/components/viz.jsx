import { useMemo, useState } from "react";
import { CATEGORY_COLORS, STATUS_COLORS, date, money } from "../lib.js";

const WEEK = 7 * 86400000;
const toDay = (d) => new Date(`${String(d).slice(0, 10)}T00:00:00Z`).getTime();

export function ClaimTimeline({ claims = [], weeks = [], intel = {} }) {
  const [hover, setHover] = useState(null);
  const lanes = useMemo(
    () =>
      claims.map((c) => ({
        ...c,
        weeks: weeks.filter((w) => w.claim_id === c.claim_id && w.state_code === c.state_code).sort((a, b) => toDay(a.week_start) - toDay(b.week_start)),
      })),
    [claims, weeks]
  );
  if (!lanes.length) return <div className="empty">No claim history</div>;

  const all = lanes.flatMap((l) => l.weeks.map((w) => toDay(w.week_start)));
  const markers = [];
  if (intel.death?.date_of_death) markers.push({ t: toDay(intel.death.date_of_death), label: "Date of death (SSA DMF)", color: CATEGORY_COLORS.fraud });
  (intel.wages || []).filter((w) => w.overlaps_claim).forEach((w) => markers.push({ t: toDay(w.quarter_start), t2: toDay(w.quarter_start) + 91 * 86400000, label: `NDNH wages ${w.quarter} · ${money(w.wages)}`, color: "#ffb020", band: true }));
  (intel.inmates || []).filter((i) => i.active_during_claim).forEach((i) => markers.push({ t: toDay(i.admit_date), t2: i.release_date ? toDay(i.release_date) : null, label: `Incarcerated · ${i.facility}`, color: CATEGORY_COLORS.fraud, band: true }));

  let t0 = Math.min(...all);
  let t1 = Math.max(...all) + WEEK;
  t0 -= WEEK * 2;
  t1 += WEEK;
  const W = 1000;
  const left = 150;
  const laneH = 34;
  const H = 34 + lanes.length * (laneH + 10) + 10;
  const x = (t) => left + ((Math.max(t0, Math.min(t1, t)) - t0) / (t1 - t0)) * (W - left - 10);
  const months = [];
  const m = new Date(t0);
  m.setUTCDate(1);
  for (let d = new Date(m); d.getTime() <= t1; d.setUTCMonth(d.getUTCMonth() + 1)) if (d.getTime() >= t0) months.push(new Date(d));

  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: "block" }}>
        {months.map((d) => (
          <g key={d.toISOString()}>
            <line x1={x(d.getTime())} x2={x(d.getTime())} y1={20} y2={H - 4} stroke="rgba(255,255,255,.05)" />
            <text x={x(d.getTime()) + 4} y={14} fill="#5d6a8c" fontSize="11">{d.toLocaleDateString("en-US", { month: "short", year: "2-digit", timeZone: "UTC" })}</text>
          </g>
        ))}
        {markers.filter((mk) => mk.band).map((mk, i) => (
          <rect key={`b${i}`} x={x(mk.t)} y={22} width={Math.max(3, x(mk.t2 ?? t1) - x(mk.t))} height={H - 28} fill={mk.color} opacity="0.1" rx="4" onMouseEnter={() => setHover({ text: mk.label })} onMouseLeave={() => setHover(null)} />
        ))}
        {lanes.map((l, i) => {
          const y = 30 + i * (laneH + 10);
          return (
            <g key={l.claim_id}>
              <rect x={0} y={y} width={W} height={laneH} fill="rgba(255,255,255,.015)" rx="8" />
              <text x={10} y={y + 15} fill="#e8edf9" fontSize="13" fontWeight="700">{l.state_code}</text>
              <text x={36} y={y + 15} fill="#8d9bbd" fontSize="10.5" fontFamily="ui-monospace,monospace">{l.claim_id}</text>
              <text x={10} y={y + 28} fill="#5d6a8c" fontSize="10.5">{l.weeks_paid} wks · {money(l.total_paid)}</text>
              {l.weeks.map((w) => {
                const xs = x(toDay(w.week_start));
                const wd = Math.max(4, x(toDay(w.week_start) + WEEK) - xs - 2);
                const c = STATUS_COLORS[w.status] || "#64748b";
                return (
                  <rect
                    key={w.week_start}
                    x={xs}
                    y={y + 6}
                    width={wd}
                    height={laneH - 12}
                    rx="3"
                    fill={c}
                    opacity={w.status === "paid" ? 0.92 : 0.75}
                    stroke={w.status === "paid" && w.work_search_contacts === 0 ? "#ffb020" : "none"}
                    strokeWidth="1.6"
                    onMouseEnter={() => setHover({ text: `${l.state_code} · week of ${date(w.week_start)} · ${w.status} (raw "${w.raw_status}")${w.paid_amount ? ` · ${money(w.paid_amount)}` : ""}${w.work_search_contacts != null ? ` · ${w.work_search_contacts} work search contacts` : ""}` })}
                    onMouseLeave={() => setHover(null)}
                  />
                );
              })}
            </g>
          );
        })}
        {markers.filter((mk) => !mk.band).map((mk, i) => (
          <g key={`m${i}`} onMouseEnter={() => setHover({ text: mk.label })} onMouseLeave={() => setHover(null)}>
            <line x1={x(mk.t)} x2={x(mk.t)} y1={20} y2={H - 4} stroke={mk.color} strokeWidth="2" strokeDasharray="4 3" />
            <text x={x(mk.t) + 5} y={30} fill={mk.color} fontSize="10.5" fontWeight="700">☠ {mk.label}</text>
          </g>
        ))}
      </svg>
      <div className="legend mt-s">
        {Object.entries(STATUS_COLORS).map(([k, c]) => (
          <span key={k} className="row" style={{ gap: 5 }}><i style={{ width: 10, height: 10, borderRadius: 3, background: c, display: "inline-block" }} />{k}</span>
        ))}
        <span className="row" style={{ gap: 5 }}><i style={{ width: 10, height: 10, borderRadius: 3, border: "1.6px solid #ffb020", display: "inline-block" }} />no work search</span>
        {hover && <span style={{ marginLeft: "auto", color: "#e8edf9" }}>{hover.text}</span>}
      </div>
    </div>
  );
}

const LINK_LABEL = { bank_account: "Bank account", device: "Device", ip_subnet: "IP subnet" };
const LINK_COLOR = { bank_account: "#ff4d6d", device: "#a78bfa", ip_subnet: "#22d3ee" };

export function LinkGraph({ links = [], name, onOpen }) {
  const [hover, setHover] = useState(null);
  const W = 560;
  const H = 360;
  const cx = W / 2;
  const cy = H / 2;
  const hubs = links.slice(0, 3);
  const nodes = [];
  const edges = [];
  const seen = new Map();
  hubs.forEach((l, i) => {
    const ang = -Math.PI / 2 + (i * 2 * Math.PI) / Math.max(hubs.length, 1);
    const hx = cx + Math.cos(ang) * 95;
    const hy = cy + Math.sin(ang) * 85;
    nodes.push({ id: `hub-${i}`, x: hx, y: hy, hub: true, link: l });
    edges.push({ x1: cx, y1: cy, x2: hx, y2: hy, color: LINK_COLOR[l.link_type] });
    const members = (l.members || []).slice(0, 12);
    members.forEach((m, j) => {
      let n = seen.get(m.applicant_key);
      if (!n) {
        const spread = Math.PI / 1.4;
        const a = ang - spread / 2 + (spread * (j + 0.5)) / members.length;
        n = { id: m.applicant_key, x: cx + Math.cos(a) * 205, y: cy + Math.sin(a) * 150, m };
        seen.set(m.applicant_key, n);
        nodes.push(n);
      }
      edges.push({ x1: hx, y1: hy, x2: n.x, y2: n.y, color: LINK_COLOR[l.link_type], thin: true });
    });
  });
  if (!hubs.length)
    return <div className="empty">No shared bank accounts, devices, or IP subnets. This claimant's identity attributes are unique.</div>;

  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%">
        {edges.map((e, i) => (
          <line key={i} {...e} stroke={e.color} strokeOpacity={e.thin ? 0.35 : 0.8} strokeWidth={e.thin ? 1 : 2.4} />
        ))}
        {nodes.map((n) =>
          n.hub ? (
            <g key={n.id}>
              <circle cx={n.x} cy={n.y} r="20" fill="#0b1224" stroke={LINK_COLOR[n.link.link_type]} strokeWidth="2" />
              <text x={n.x} y={n.y + 4} textAnchor="middle" fontSize="11" fontWeight="800" fill={LINK_COLOR[n.link.link_type]}>{n.link.applicant_count}</text>
              <text x={n.x} y={n.y + 34} textAnchor="middle" fontSize="10.5" fill="#8d9bbd">{LINK_LABEL[n.link.link_type]}</text>
            </g>
          ) : (
            <g key={n.id} style={{ cursor: "pointer" }} onClick={() => onOpen && onOpen(n.id)} onMouseEnter={() => setHover(n)} onMouseLeave={() => setHover(null)}>
              <circle cx={n.x} cy={n.y} r={n.m.flagged ? 9 : 7} fill={n.m.flagged ? CATEGORY_COLORS.fraud : "#334166"} stroke="#070b16" strokeWidth="2" />
              {n.m.flagged && <circle cx={n.x} cy={n.y} r="13" fill="none" stroke={CATEGORY_COLORS.fraud} strokeOpacity="0.35" />}
            </g>
          )
        )}
        <circle cx={cx} cy={cy} r="28" fill="url(#centerGrad)" stroke="#e8edf9" strokeWidth="2" />
        <defs>
          <radialGradient id="centerGrad">
            <stop offset="0" stopColor="#ff4d6d" />
            <stop offset="1" stopColor="#7f1d3a" />
          </radialGradient>
        </defs>
        <text x={cx} y={cy + 4} textAnchor="middle" fontSize="12" fontWeight="800" fill="#fff">{(name || "?").split(" ").map((s) => s[0]).join("").slice(0, 2)}</text>
      </svg>
      {hover && (
        <div className="tooltip" style={{ left: `${(hover.x / W) * 100}%`, top: `${(hover.y / H) * 100}%`, minWidth: 190 }}>
          <strong>{hover.m.name}</strong>
          <div className="muted" style={{ fontSize: 11.5 }}>{(hover.m.states || []).join(", ")} · ML {Math.round((hover.m.ml_score || 0) * 100)}</div>
          <div style={{ fontSize: 11.5, color: hover.m.flagged ? "#ff4d6d" : "#2dd4bf" }}>{hover.m.flagged ? "Flagged" : "Not flagged"}</div>
        </div>
      )}
      <div className="legend">
        {Object.entries(LINK_LABEL).map(([k, v]) => (
          <span key={k} className="row" style={{ gap: 5 }}><i style={{ width: 14, height: 3, background: LINK_COLOR[k], display: "inline-block" }} />{v}</span>
        ))}
        <span className="row" style={{ gap: 5 }}><i style={{ width: 9, height: 9, borderRadius: 9, background: CATEGORY_COLORS.fraud, display: "inline-block" }} />flagged claimant</span>
      </div>
    </div>
  );
}

export function RocCurve({ points = [], auc }) {
  const S = 260;
  const pad = 30;
  const p = points.map((r) => [pad + r.fpr * (S - pad - 8), S - pad - r.tpr * (S - pad - 8)]);
  const d = p.map((q, i) => `${i ? "L" : "M"}${q[0]},${q[1]}`).join(" ");
  const area = `${d} L${S - 8},${S - pad} L${pad},${S - pad} Z`;
  return (
    <svg viewBox={`0 0 ${S} ${S}`} width="100%" style={{ maxWidth: 340 }}>
      <defs>
        <linearGradient id="rocFill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#a78bfa" stopOpacity="0.45" />
          <stop offset="1" stopColor="#a78bfa" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <rect x={pad} y={8} width={S - pad - 8} height={S - pad - 8} fill="none" stroke="#1d2a4d" />
      <line x1={pad} y1={S - pad} x2={S - 8} y2={8} stroke="#2a3a66" strokeDasharray="4 4" />
      {p.length > 1 && <path d={area} fill="url(#rocFill)" />}
      {p.length > 1 && <path d={d} fill="none" stroke="#a78bfa" strokeWidth="2.5" />}
      <text x={S / 2 + 10} y={S - 8} textAnchor="middle" fill="#5d6a8c" fontSize="10">False positive rate</text>
      <text x={10} y={S / 2} textAnchor="middle" fill="#5d6a8c" fontSize="10" transform={`rotate(-90 10 ${S / 2})`}>True positive rate</text>
      {auc != null && <text x={S - 18} y={S - pad - 12} textAnchor="end" fill="#e8edf9" fontSize="16" fontWeight="800">AUC {auc.toFixed(3)}</text>}
    </svg>
  );
}

export function Confusion({ tp = 0, fp = 0, tn = 0, fn = 0 }) {
  const max = Math.max(tp, fp, tn, fn, 1);
  const cell = (v, good, label) => (
    <div style={{ background: good ? `rgba(45,212,191,${0.08 + (v / max) * 0.4})` : `rgba(255,77,109,${0.06 + (v / max) * 0.45})`, borderRadius: 10, padding: 14, textAlign: "center" }}>
      <div className="num" style={{ fontSize: 22, fontWeight: 800 }}>{v.toLocaleString()}</div>
      <div className="muted" style={{ fontSize: 11 }}>{label}</div>
    </div>
  );
  return (
    <div style={{ display: "grid", gridTemplateColumns: "70px 1fr 1fr", gap: 8, alignItems: "center", fontSize: 11.5 }}>
      <span />
      <span className="muted" style={{ textAlign: "center" }}>Predicted fraud</span>
      <span className="muted" style={{ textAlign: "center" }}>Predicted clean</span>
      <span className="muted">Actual fraud</span>
      {cell(tp, true, "True positive")}
      {cell(fn, false, "Missed")}
      <span className="muted">Actual clean</span>
      {cell(fp, false, "False alarm")}
      {cell(tn, true, "True negative")}
    </div>
  );
}

export function Markdown({ text = "" }) {
  const html = useMemo(() => renderMd(text), [text]);
  return <div className="md" dangerouslySetInnerHTML={{ __html: html }} />;
}

function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function inline(s) {
  return esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer" style="color:#22d3ee">$1</a>');
}
function renderMd(text) {
  const lines = text.split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    const l = lines[i];
    if (/^\s*\|/.test(l)) {
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
      const cells = (r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      const body = rows.filter((r) => !/^\s*\|\s*:?-{2,}/.test(r));
      out.push(`<div class="scroll-x"><table><thead><tr>${cells(body[0]).map((c) => `<th>${inline(c)}</th>`).join("")}</tr></thead><tbody>${body.slice(1).map((r) => `<tr>${cells(r).map((c) => `<td>${inline(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
      continue;
    }
    if (/^\s*[-*]\s+/.test(l)) {
      const items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*]\s+/, ""));
      out.push(`<ul>${items.map((x) => `<li>${inline(x)}</li>`).join("")}</ul>`);
      continue;
    }
    if (/^\s*\d+\.\s+/.test(l)) {
      const items = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*\d+\.\s+/, ""));
      out.push(`<ol>${items.map((x) => `<li>${inline(x)}</li>`).join("")}</ol>`);
      continue;
    }
    const h = l.match(/^(#{1,4})\s+(.*)/);
    if (h) out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`);
    else if (l.trim()) out.push(`<p>${inline(l)}</p>`);
    i++;
  }
  return out.join("");
}
