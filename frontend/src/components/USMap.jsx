import { geoPath } from "d3-geo";
import { useMemo, useRef, useState } from "react";
import { feature, mesh } from "topojson-client";
import us from "us-atlas/states-albers-10m.json";
import { money, moneyShort, num, pct, rampColor } from "../lib.js";

const LABEL_OFFSET = { 25: [58, -18], 34: [52, 14], 36: [-6, 6], 12: [14, 0], 42: [-4, 0], 6: [-8, 10], 53: [0, 4] };

export default function USMap({ states = [], pairs = [], selected, onSelect, metric = "flag_rate" }) {
  const wrap = useRef(null);
  const [hover, setHover] = useState(null);
  const path = useMemo(() => geoPath(), []);
  const features = useMemo(() => feature(us, us.objects.states).features, []);
  const borders = useMemo(() => mesh(us, us.objects.states, (a, b) => a !== b), []);
  const byFips = useMemo(() => Object.fromEntries(states.map((s) => [String(s.fips).padStart(2, "0"), s])), [states]);
  const byCode = useMemo(() => Object.fromEntries(states.map((s) => [s.state_code, s])), [states]);
  const centroid = useMemo(() => {
    const c = {};
    for (const f of features) c[f.id] = path.centroid(f);
    return c;
  }, [features, path]);

  const vals = states.map((s) => s[metric] || 0);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals, 0.0001);
  const topPairs = [...pairs].sort((a, b) => b.claimants - a.claimants).slice(0, 12);
  const maxPair = Math.max(1, ...topPairs.map((p) => p.claimants));

  const fipsOf = (code) => byCode[code] && String(byCode[code].fips).padStart(2, "0");

  const arcs = topPairs
    .map((p) => {
      const a = centroid[fipsOf(p.state_a)];
      const b = centroid[fipsOf(p.state_b)];
      if (!a || !b) return null;
      const mx = (a[0] + b[0]) / 2;
      const my = (a[1] + b[1]) / 2;
      const dx = b[0] - a[0];
      const dy = b[1] - a[1];
      const d = Math.hypot(dx, dy);
      const k = Math.min(0.32, 60 / d + 0.12);
      const cx = mx + dy * k * (dx > 0 ? 1 : -1) * 0.6;
      const cy = my - Math.abs(dx) * k - d * 0.08;
      return { ...p, d: `M${a[0]},${a[1]} Q${cx},${cy} ${b[0]},${b[1]}`, w: 1.2 + (p.claimants / maxPair) * 4.5 };
    })
    .filter(Boolean);

  const move = (e, s) => {
    const r = wrap.current.getBoundingClientRect();
    setHover({ s, x: e.clientX - r.left, y: e.clientY - r.top, w: r.width });
  };

  return (
    <div className="map-wrap" ref={wrap} onMouseLeave={() => setHover(null)}>
      <svg viewBox="0 0 975 610">
        <defs>
          <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="6" result="b" />
            <feMerge>
              <feMergeNode in="b" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
          <linearGradient id="arcGrad" x1="0" x2="1">
            <stop offset="0" stopColor="#ff4d6d" stopOpacity="0.2" />
            <stop offset="0.5" stopColor="#ff4d6d" />
            <stop offset="1" stopColor="#ffb020" stopOpacity="0.6" />
          </linearGradient>
        </defs>
        <g>
          {features.map((f) => {
            const s = byFips[f.id];
            const t = s ? ((s[metric] || 0) - lo) / (hi - lo || 1) : 0;
            const isSel = s && selected === s.state_code;
            return (
              <path
                key={f.id}
                d={path(f)}
                className={`state-path ${s ? "live" : ""}`}
                fill={s ? rampColor(0.15 + t * 0.85) : "#111a33"}
                stroke={isSel ? "#e8edf9" : s ? "rgba(255,255,255,.35)" : "#1a2546"}
                strokeWidth={isSel ? 2.4 : s ? 1 : 0.6}
                filter={isSel ? "url(#glow)" : undefined}
                onMouseMove={s ? (e) => move(e, s) : undefined}
                onMouseLeave={() => setHover(null)}
                onClick={s ? () => onSelect && onSelect(s.state_code) : undefined}
              />
            );
          })}
          <path d={path(borders)} fill="none" stroke="#0a1024" strokeWidth="0.5" pointerEvents="none" opacity="0.6" />
        </g>
        <g pointerEvents="none">
          {arcs.map((a) => (
            <g key={`${a.state_a}-${a.state_b}`}>
              <path d={a.d} stroke="#ff4d6d" strokeOpacity="0.12" strokeWidth={a.w + 4} fill="none" />
              <path d={a.d} className="arc" stroke="url(#arcGrad)" strokeWidth={a.w} />
            </g>
          ))}
        </g>
        <g pointerEvents="none">
          {states.map((s) => {
            const f = String(s.fips).padStart(2, "0");
            const c = centroid[f];
            if (!c) return null;
            const off = LABEL_OFFSET[Number(f)] || [0, 0];
            const lx = c[0] + off[0];
            const ly = c[1] + off[1];
            return (
              <g key={s.state_code}>
                <circle cx={c[0]} cy={c[1]} r="7" fill="#22d3ee" className="ping" />
                <circle cx={c[0]} cy={c[1]} r="2.6" fill="#22d3ee" />
                {(off[0] !== 0 || off[1] !== 0) && Math.hypot(off[0], off[1]) > 20 && (
                  <line x1={c[0]} y1={c[1]} x2={lx - 16} y2={ly - 4} stroke="rgba(232,237,249,.4)" strokeWidth="0.8" />
                )}
                <text x={lx} y={ly - 8} textAnchor="middle" fill="#fff" fontSize="15" fontWeight="800" style={{ paintOrder: "stroke", stroke: "#070b16", strokeWidth: 3 }}>
                  {s.state_code}
                </text>
                <text x={lx} y={ly + 7} textAnchor="middle" fill="#ffd0d9" fontSize="11" fontWeight="700" style={{ paintOrder: "stroke", stroke: "#070b16", strokeWidth: 3 }}>
                  {num(s.flagged)} flagged
                </text>
              </g>
            );
          })}
        </g>
      </svg>
      {hover && (
        <div className="tooltip" style={{ left: Math.min(hover.x + 16, hover.w - 250), top: hover.y + 12 }}>
          <div className="row between">
            <strong style={{ fontSize: 14 }}>{hover.s.state_name}</strong>
            <span className="badge fraud">{pct(hover.s.flag_rate)} flagged</span>
          </div>
          <div className="muted" style={{ fontSize: 11.5, marginBottom: 8 }}>{hover.s.agency} · {hover.s.system}</div>
          <dl className="kv">
            <dt>Claimants</dt><dd className="num">{num(hover.s.claimants)}</dd>
            <dt>Events via {hover.s.channel || "Zerobus"}</dt><dd className="num">{num(hover.s.events)}</dd>
            <dt>Benefits paid</dt><dd className="num">{money(hover.s.total_paid)}</dd>
            <dt>Fraud / ineligible</dt><dd className="num"><span style={{ color: "#ff4d6d" }}>{num(hover.s.fraud)}</span> / <span style={{ color: "#ffb020" }}>{num(hover.s.ineligible)}</span></dd>
            <dt>At risk</dt><dd className="num" style={{ color: "#ff4d6d", fontWeight: 700 }}>{moneyShort(hover.s.at_risk)}</dd>
            {hover.s.top_finding && (<><dt>Top finding</dt><dd>{hover.s.top_finding}</dd></>)}
          </dl>
        </div>
      )}
    </div>
  );
}
