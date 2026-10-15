import { useCallback, useEffect, useRef, useState } from "react";

const PERSONA_KEY = "dol_persona";
export const getPersona = () => localStorage.getItem(PERSONA_KEY) || "investigator";
export const setPersona = (id) => {
  localStorage.setItem(PERSONA_KEY, id);
  window.location.reload();
};

export async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", "X-DOL-Persona": getPersona() },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      detail = JSON.parse(text).detail || text;
    } catch {}
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json();
}

export function useApi(path, { refresh = 0, deps = [] } = {}) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const alive = useRef(true);
  const load = useCallback(async () => {
    if (!path) return;
    try {
      const data = await api(path);
      if (alive.current) setState({ data, error: null, loading: false });
    } catch (error) {
      if (alive.current) setState((s) => ({ ...s, error, loading: false }));
    }
  }, [path]);
  useEffect(() => {
    alive.current = true;
    setState((s) => ({ ...s, loading: true }));
    load();
    let t;
    if (refresh) t = setInterval(load, refresh);
    return () => {
      alive.current = false;
      clearInterval(t);
    };
  }, [load, refresh, ...deps]);
  return { ...state, reload: load };
}

export function useRoute() {
  const parse = () => (window.location.hash.replace(/^#/, "") || "/").split("?")[0];
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const on = () => {
      setRoute(parse());
      window.scrollTo({ top: 0 });
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export const go = (path) => (window.location.hash = path);

const usd0 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
export const money = (v) => (v == null ? "—" : usd0.format(v));
export const moneyShort = (v) => {
  if (v == null) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
  return usd0.format(v);
};
export const num = (v) => (v == null ? "—" : Number(v).toLocaleString("en-US"));
export const pct = (v, d = 1) => (v == null ? "—" : `${(v * 100).toFixed(d)}%`);
export const date = (v) => (v ? new Date(v).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "—");
export const time = (v) => (v ? new Date(v).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) : "—");
export const ago = (v) => {
  if (!v) return "—";
  const s = Math.max(0, (Date.now() - new Date(v).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
};

export const STATUS_COLORS = {
  filed: "#64748b",
  pending: "#f59e0b",
  paid: "#10b981",
  denied: "#ef4444",
  appealed: "#8b5cf6",
  exhausted: "#94a3b8",
};

export const CATEGORY_COLORS = { fraud: "#ff4d6d", eligibility: "#ffb020", clean: "#2dd4bf" };
export const TECH_COLORS = { rules: "#60a5fa", ml: "#a78bfa", agent: "#22d3ee" };

export const VERDICT_STYLE = {
  FRAUD: { bg: "rgba(255,77,109,.16)", fg: "#ff4d6d", label: "Fraud" },
  INELIGIBLE: { bg: "rgba(255,176,32,.16)", fg: "#ffb020", label: "Ineligible" },
  ELIGIBLE: { bg: "rgba(45,212,191,.14)", fg: "#2dd4bf", label: "Eligible" },
  NEEDS_REVIEW: { bg: "rgba(148,163,184,.14)", fg: "#cbd5e1", label: "Needs review" },
};

export function rampColor(t) {
  const a = [58, 36, 66];
  const b = [255, 77, 109];
  const x = Math.max(0, Math.min(1, t));
  return `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * x)).join(",")})`;
}
