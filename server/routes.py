import contextvars
import copy
import json
import os
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from server import db, investigations
from server import rule_studio as rs
from server import queries as Q
from server.config import (
    DEFAULT_PERSONA, IS_DATABRICKS_APP, PERSONAS, UC_CATALOG, UC_SCHEMA, current_persona, get_workspace_client, get_workspace_host,
    persona_credentials, persona_var,
)
from server.sql import SqlError, cached, clear_cache, parallel, run_sql
from src.pipelines.state_specs import CHANNEL_LABELS, SHARE_STATES, STATE_SPECS

router = APIRouter()

DEFAULT_CONFIG = {"genie_agent_id": os.environ.get("GENIE_AGENT_ID", ""), "ml_flag_threshold": "", "queue_limit": "300", "agency_banner": "U.S. Dept. of Labor · ETA"}
ML_FEATURES = [
    ("shared_bank_claimants", "Shared payment account", lambda v: "Unique" if v <= 1 else f"{int(v)} claimants", lambda v: v >= 3),
    ("shared_device_claimants", "Shared device", lambda v: "Unique" if v <= 1 else f"{int(v)} claimants", lambda v: v >= 3),
    ("shared_subnet_claimants", "Shared IP subnet", lambda v: "Unique" if v <= 1 else f"{int(v)} claimants", lambda v: v >= 3),
    ("employer_claimants", "Employer claimants", lambda v: f"{int(v)}", lambda v: v >= 8),
    ("base_quarters_with_wages", "Base quarters with wages", lambda v: f"{int(v)} of 4", lambda v: v <= 1),
    ("high_quarter_share", "High-quarter wage share", lambda v: f"{v * 100:.0f}%", lambda v: v >= 0.99),
    ("wba_to_state_max", "WBA vs state max", lambda v: f"{v * 100:.0f}%", lambda v: v >= 0.99),
    ("state_count", "States claimed", lambda v: f"{int(v)}", lambda v: v > 1),
]


def analyst(request: Request) -> str:
    return request.headers.get("X-Forwarded-Email") or request.headers.get("X-Forwarded-Preferred-Username") or "analyst@dol.gov"


def config() -> dict:
    def load():
        cfg = dict(DEFAULT_CONFIG)
        for r in db.safe_query("SELECT key, value FROM app_config"):
            if r["value"] != "" or r["key"] not in cfg:
                cfg[r["key"]] = r["value"]
        return cfg
    return cached("config", 15, load)


def disabled_rules() -> list[str]:
    return cached("disabled", 15, lambda: [r["rule_id"] for r in db.safe_query("SELECT rule_id FROM rule_toggles WHERE enabled = false")])


def ml_threshold() -> float:
    v = config().get("ml_flag_threshold")
    try:
        if v not in (None, ""):
            return float(v)
    except ValueError:
        pass
    rows = cached("ml_thr", 300, lambda: run_sql(Q.ML_THRESHOLD))
    return float(rows[0]["value"]) if rows else 0.5


def fsql(body: str) -> str:
    return Q.with_flags(disabled_rules(), ml_threshold(), body)


def sql_or_500(fn):
    try:
        return fn()
    except SqlError as e:
        raise HTTPException(status_code=502, detail=f"Warehouse query failed: {e}")


@router.get("/health")
def health():
    cfg = config()
    lakebase_ok = False
    if db.pool is not None:
        try:
            db.query("SELECT 1 AS ok")
            lakebase_ok = True
        except Exception as e:  # noqa: BLE001
            print(f"Lakebase health failed: {e}")
    try:
        cached("wh_ok", 120, lambda: run_sql("SELECT 1 AS ok"))
        wh_ok = True
    except Exception:  # noqa: BLE001
        wh_ok = False
    return {
        "ok": True,
        "lakebase": lakebase_ok,
        "lakebase_endpoint": os.environ.get("ENDPOINT_NAME", ""),
        "lakebase_branch": (os.environ.get("ENDPOINT_NAME", "").split("/branches/")[-1].split("/")[0] or "production"),
        "warehouse": wh_ok,
        "warehouse_id": os.environ.get("DATABRICKS_WAREHOUSE_ID", ""),
        "catalog": UC_CATALOG,
        "schema": UC_SCHEMA,
        "genie_agent_id": cfg.get("genie_agent_id"),
        "agency_banner": cfg.get("agency_banner"),
    }


@router.get("/overview")
def overview():
    def build():
        r = parallel(
            kpis=lambda: run_sql(fsql(Q.KPIS)),
            states=lambda: run_sql(fsql(Q.STATES)),
            techniques=lambda: run_sql(fsql(Q.TECHNIQUES)),
            findings=lambda: run_sql(fsql(Q.FINDINGS)),
            top=lambda: run_sql(fsql(Q.TOP_CASES)),
            pairs=lambda: run_sql(Q.PAIRS),
        )
        k = r["kpis"][0]
        k["flag_rate"] = (k["flagged"] or 0) / max(k["claimants"] or 1, 1)
        states = r["states"]
        for s in states:
            s["fips"] = STATE_SPECS[s["state_code"]]["fips"]
            s["channel"] = CHANNEL_LABELS[STATE_SPECS[s["state_code"]]["transport"]]
        return {"kpis": k, "states": states, "techniques": r["techniques"][0], "findings": r["findings"], "top_cases": r["top"], "pairs": r["pairs"], "updated_at": datetime.now(timezone.utc).isoformat()}
    return sql_or_500(lambda: cached(f"overview:{disabled_rules()}:{ml_threshold()}", 30, build))


@router.get("/ingest/recent")
def ingest_recent():
    return sql_or_500(lambda: {"events": cached("recent", 5, lambda: run_sql(Q.RECENT))})


def _mask(payload: dict, ssn_path: str) -> dict:
    keys = ssn_path.lstrip("$.").split(".")
    node = payload
    for k in keys[:-1]:
        node = node.get(k, {})
    if keys[-1] in node:
        digits = "".join(ch for ch in str(node[keys[-1]]) if ch.isdigit())
        node[keys[-1]] = f"•••-••-{digits[-4:]}" if "-" in str(node[keys[-1]]) else f"•••••{digits[-4:]}"
    return payload


@router.get("/states/{code}")
def state_detail(code: str):
    code = code.upper()
    if code not in STATE_SPECS:
        raise HTTPException(404, "Unknown state")

    def build():
        r = parallel(
            mix=lambda: run_sql(Q.STATE_STATUS_MIX, {"s": code}),
            sample=lambda: run_sql(Q.STATE_SAMPLE, {"s": code}),
            findings=lambda: run_sql(fsql(Q.STATE_FINDINGS), {"s": code}),
        )
        spec = copy.deepcopy(STATE_SPECS[code])
        sample = json.loads(r["sample"][0]["payload"]) if r["sample"] else {}
        return {"spec": spec, "sample_payload": _mask(sample, spec["fields"]["ssn"]), "status_mix": r["mix"], "findings": r["findings"]}
    return sql_or_500(lambda: cached(f"state:{code}:{disabled_rules()}:{ml_threshold()}", 60, build))


def case_statuses(keys: list[str]) -> dict:
    if not keys:
        return {}
    return {r["applicant_key"]: r["status"] for r in db.safe_query("SELECT applicant_key, status FROM cases WHERE applicant_key = ANY(%s)", (keys,))}


@router.get("/cases")
def cases(state: str | None = None, category: str | None = None, technique: str | None = None):
    limit = int(config().get("queue_limit") or 300)
    params = {"state": state or None, "category": category or None, "technique": technique or None}
    rows = sql_or_500(lambda: cached(f"cases:{params}:{disabled_rules()}:{ml_threshold()}", 20, lambda: run_sql(fsql(Q.CASES.replace("{limit}", str(min(limit, 2000)))), params)))
    statuses = case_statuses([r["applicant_key"] for r in rows])
    out = []
    for r in rows:
        findings = list(r["rule_names"] or [])
        if r["ml_flag"]:
            findings.append("Behavioral fraud pattern")
        cats = (["fraud"] if r["is_fraud"] else []) + (["eligibility"] if r["is_inelig"] else [])
        out.append({**r, "findings": findings, "categories": cats, "case_status": statuses.get(r["applicant_key"], "new")})
    return {"cases": out, "totals": {"claimants": len(out), "at_risk": sum(r["at_risk"] or 0 for r in out)}}


def _d(v):
    return date.fromisoformat(str(v)[:10]) if v else None


@router.get("/applicants/{key}")
def applicant(key: str):
    if not key.isalnum():
        raise HTTPException(400, "Invalid key")
    p = {"k": key}
    jobs = {
        "flags": lambda: run_sql(fsql(Q.APPLICANT), p),
        "claims": lambda: run_sql(Q.CLAIMS, p),
        "weeks": lambda: run_sql(Q.WEEKS, p),
        "rules": lambda: run_sql(Q.RULE_HITS, p),
        "custom": lambda: run_sql(Q.CUSTOM_HITS, p),
        "ml": lambda: run_sql(Q.ML, p),
        "agent": lambda: run_sql(Q.AGENT, p),
        "links": lambda: run_sql(Q.LINKS, p),
        **{f"intel_{k}": (lambda s=s: run_sql(s, p)) for k, s in Q.INTEL.items()},
    }
    r = sql_or_500(lambda: parallel(**jobs))
    if not r["flags"]:
        raise HTTPException(404, "Claimant not found")
    f = r["flags"][0]
    claims = r["claims"]
    thr = ml_threshold()
    disabled = set(disabled_rules())

    paid_ranges = [(_d(c["first_week"]), _d(c["last_paid_week"]), c["employer_name"]) for c in claims if c["last_paid_week"]]
    wages = []
    for w in r["intel_wages"]:
        qs = _d(w["quarter_start"])
        qe = date(qs.year + (qs.month + 2) // 12, (qs.month + 2) % 12 + 1, 1) if qs else None
        w["overlaps_claim"] = any(qs and a and b and qs <= b and qe > a and w["employer_name"] != emp for a, b, emp in paid_ranges)
        wages.append(w)
    inmates = []
    for i in r["intel_inmates"]:
        adm, rel = _d(i["admit_date"]), _d(i["release_date"])
        i["active_during_claim"] = any(a and b and adm <= b and (rel is None or rel >= a) for a, b, _ in paid_ranges)
        inmates.append(i)
    intel = {
        "death": r["intel_death"][0] if r["intel_death"] else None,
        "inmates": inmates,
        "wages": wages,
        "identity": r["intel_identity"][0] if r["intel_identity"] else None,
        "dnp": r["intel_dnp"],
    }

    rules = [{**x, "hit": bool(x["evidence"]) and x["rule_id"] not in disabled, "enabled": x["rule_id"] not in disabled} for x in r["rules"]]
    rules += [
        {**x, "description": "Analyst-authored rule promoted from the Rule studio", "custom": True, "hit": x["rule_id"] not in disabled, "enabled": x["rule_id"] not in disabled}
        for x in r["custom"]
    ]

    ml = None
    if r["ml"]:
        m = r["ml"][0]
        ml = {
            "score": m["ml_score"], "risk_band": m["risk_band"], "drivers": m["drivers"] or [], "model_version": m["model_version"], "threshold": thr,
            "flag": m["ml_score"] >= thr,
            "features": [{"name": n, "label": lbl, "display": fmt(m[n] or 0), "elevated": bool(hot(m[n] or 0))} for n, lbl, fmt, hot in ML_FEATURES if n in m],
        }

    agent = None
    if r["agent"] and r["agent"][0]["status"] == "completed":
        a = r["agent"][0]
        agent = {**a, "steps": json.loads(a.get("steps_json") or "[]")}
    latest = db.safe_query(
        "SELECT * FROM investigation_runs WHERE applicant_key = %s AND status = 'completed' ORDER BY created_at DESC LIMIT 1", (key,)
    )
    if latest:
        lr = latest[0]
        if not agent or str(lr["completed_at"] or "") > str(agent.get("completed_at") or ""):
            agent = {
                "verdict": lr["verdict"], "confidence": lr["confidence"], "summary": lr["summary"], "report": lr["report"],
                "steps": json.loads(lr["steps_json"] or "[]"), "sql_count": lr["sql_count"], "completed_at": lr["completed_at"].isoformat() if lr["completed_at"] else None,
                "conversation_id": lr["conversation_id"],
            }

    links = r["links"]
    member_keys = sorted({k for l in links for k in (l["member_keys"] or [])})
    members = {}
    if member_keys:
        members = {m["applicant_key"]: m for m in sql_or_500(lambda: run_sql(fsql(Q.MEMBERS), {"keys": json.dumps(member_keys)}))}
    for l in links:
        l["members"] = [members[k] for k in (l["member_keys"] or []) if k in members]

    if f["is_fraud"]:
        cat, headline = "fraud", "Likely fraud"
    elif f["is_inelig"]:
        cat, headline = "eligibility", "Ineligible · overpayment"
    else:
        cat, headline = "clean", "No integrity issues"
    detail = f"Rules {f['rule_hits']} hit{'s' if f['rule_hits'] != 1 else ''} · ML {round(f['ml_score'] * 100)} · Genie {(agent or {}).get('verdict', 'not run').replace('_', ' ').lower()}"

    profile = {k: f[k] for k in ("applicant_key", "first_name", "last_name", "ssn_last4", "dob", "states", "home_state", "claim_count", "weeks_paid", "total_paid", "latest_status")}
    case_rows = db.safe_query("SELECT status, assigned_to, updated_at FROM cases WHERE applicant_key = %s", (key,))
    return {
        "profile": profile,
        "overall": {"category": cat, "headline": headline, "detail": detail, "risk_score": f["risk_score"], "at_risk": f["at_risk"]},
        "claims": claims,
        "weeks": r["weeks"],
        "rules": rules,
        "ml": ml,
        "agent": agent,
        "agent_configured": bool(config().get("genie_agent_id")),
        "intel": intel,
        "links": links,
        "case": case_rows[0] if case_rows else None,
        "notes": db.safe_query("SELECT id, author, body, created_at FROM case_notes WHERE applicant_key = %s ORDER BY created_at DESC", (key,)),
        "dispositions": db.safe_query("SELECT id, decision, rationale, author AS analyst, created_at FROM analyst_dispositions WHERE applicant_key = %s ORDER BY created_at DESC", (key,)),
        "investigations": db.safe_query("SELECT id, status, verdict, requested_by, created_at FROM investigation_runs WHERE applicant_key = %s ORDER BY created_at DESC LIMIT 20", (key,)),
    }


def ensure_case(key: str, status: str | None = None):
    db.execute(
        "INSERT INTO cases (applicant_key, status, updated_at) VALUES (%s, %s, now()) ON CONFLICT (applicant_key) DO UPDATE SET status = COALESCE(%s, cases.status), updated_at = now()",
        (key, status or "in_review", status),
    )


class DispositionIn(BaseModel):
    decision: str
    rationale: str = ""


class NoteIn(BaseModel):
    body: str


class CaseIn(BaseModel):
    status: str


def require_lakebase():
    if db.pool is None:
        raise HTTPException(503, "Lakebase is not configured for this app")


@router.post("/applicants/{key}/disposition")
def disposition(key: str, body: DispositionIn, request: Request):
    require_lakebase()
    if body.decision not in ("confirmed_fraud", "ineligible", "refer_oig", "cleared"):
        raise HTTPException(400, "Unknown decision")
    ensure_case(key, "closed" if body.decision in ("confirmed_fraud", "ineligible", "cleared") else "referred")
    rows = db.execute(
        "INSERT INTO analyst_dispositions (id, applicant_key, source, decision, rationale, author) VALUES (gen_random_uuid()::text, %s, 'analyst', %s, %s, %s) RETURNING id, decision, rationale, author AS analyst, created_at",
        (key, body.decision, body.rationale, analyst(request)),
    )
    return rows[0]


@router.post("/applicants/{key}/notes")
def add_note(key: str, body: NoteIn, request: Request):
    require_lakebase()
    ensure_case(key)
    rows = db.execute(
        "INSERT INTO case_notes (id, applicant_key, author, body) VALUES (gen_random_uuid()::text, %s, %s, %s) RETURNING id, author, body, created_at",
        (key, analyst(request), body.body),
    )
    return rows[0]


@router.put("/applicants/{key}/case")
def set_case(key: str, body: CaseIn):
    require_lakebase()
    ensure_case(key, body.status)
    return {"ok": True}


@router.post("/applicants/{key}/investigate")
def investigate(key: str, request: Request):
    agent_id = config().get("genie_agent_id")
    if not agent_id:
        raise HTTPException(400, "No Genie agent configured")
    rows = run_sql(Q.APPLICANT.replace("FROM flags", f"FROM {Q.T}.gold_applicant_profile"), {"k": key})
    if not rows:
        raise HTTPException(404, "Claimant not found")
    p = rows[0]
    if db.pool is not None:
        ensure_case(key)
    run_id = investigations.start(agent_id, key, f"{p['first_name']} {p['last_name']}", p["states"], analyst(request))
    return {"run_id": run_id}


@router.get("/investigations/{run_id}")
def investigation(run_id: str):
    r = investigations.get(run_id)
    if not r:
        raise HTTPException(404, "Unknown investigation")
    return r


@router.get("/detection")
def detection():
    def build():
        r = parallel(
            rules=lambda: run_sql(Q.RULE_STATS),
            metrics=lambda: run_sql(Q.MODEL_METRICS),
            roc=lambda: run_sql(Q.MODEL_ROC),
            importance=lambda: run_sql(Q.MODEL_IMPORTANCE),
            reviews=lambda: run_sql(Q.AGENT_REVIEWS),
        )
        return r
    r = sql_or_500(lambda: cached("detection", 60, build))
    disabled = set(disabled_rules())
    metrics = {m["metric"]: m["value"] for m in r["metrics"]}
    meta = r["metrics"][0] if r["metrics"] else {}
    host = get_workspace_host().rstrip("/")
    agent_id = config().get("genie_agent_id")
    reviews = r["reviews"]
    verdicts = {}
    for v in reviews:
        verdicts[v["verdict"]] = verdicts.get(v["verdict"], 0) + 1
    model_name = meta.get("model_name") or ""
    return {
        "code": _attempt(code_links, {}),
        "rules": [{**x, "enabled": x["rule_id"] not in disabled} for x in r["rules"]],
        "model": {
            "metrics": metrics, "roc": r["roc"], "importance": r["importance"], "model_name": model_name, "model_version": meta.get("model_version"),
            "trained_at": meta.get("trained_at"), "run_id": meta.get("run_id"),
            "experiment_url": f"{host}/explore/data/models/{model_name.replace('.', '/')}" if model_name else None,
        },
        "agent": {
            "space_id": agent_id, "url": f"{host}/genie/rooms/{agent_id}" if agent_id else None, "reviews": reviews,
            "verdicts": [{"verdict": k, "n": v} for k, v in sorted(verdicts.items(), key=lambda kv: -kv[1])],
            "avg_queries": (sum(v["sql_count"] or 0 for v in reviews) / len(reviews)) if reviews else 0,
        },
    }


class ToggleIn(BaseModel):
    enabled: bool


@router.put("/rules/{rule_id}")
def toggle_rule(rule_id: str, body: ToggleIn):
    require_lakebase()
    if not Q.RULE_ID.match(rule_id):
        raise HTTPException(400, "Invalid rule id")
    db.execute(
        "INSERT INTO rule_toggles (rule_id, enabled, label, updated_at) VALUES (%s, %s, %s, now()) ON CONFLICT (rule_id) DO UPDATE SET enabled = EXCLUDED.enabled, updated_at = now()",
        (rule_id, body.enabled, rule_id),
    )
    clear_cache()
    return {"ok": True}


def persona_principal(name: str) -> str | None:
    creds = cached(f"persona_creds:{name}", 600, lambda: persona_credentials(name) or {})
    return creds.get("client_id")


@router.get("/personas")
def personas():
    return {
        "current": current_persona(),
        "personas": [
            {"id": k, **{f: p[f] for f in ("label", "role", "identity")}, "available": k == DEFAULT_PERSONA or bool(persona_principal(k))}
            for k, p in PERSONAS.items()
        ],
    }


def run_as(persona: str, fn):
    def inner():
        persona_var.set(persona)
        return fn()
    return contextvars.copy_context().run(inner)


def safe_probe() -> dict:
    try:
        rows = run_sql(Q.ACCESS_PROBE)
        return {**rows[0], "error": None} if rows else {}
    except SqlError as e:
        return {"error": str(e)[:200]}


def is_access_admin(request: Request) -> bool:
    if not IS_DATABRICKS_APP:
        return True
    admins = {a.strip().lower() for a in os.environ.get("ACCESS_ADMINS", "").split(",") if a.strip()}
    return analyst(request).lower() in admins


@router.get("/governance")
def governance(request: Request):
    def build():
        probes = {f"probe:{k}": (lambda k=k: run_as(k, lambda: safe_probe())) for k in PERSONAS}
        r = parallel(
            entitlements=lambda: run_sql(Q.ENTITLEMENTS, as_service=True),
            tags=lambda: run_sql(Q.COLUMN_TAGS, as_service=True),
            **probes,
        )
        try:
            policies = get_workspace_client().api_client.do("GET", f"/api/2.1/unity-catalog/policies/SCHEMA/{UC_CATALOG}.{UC_SCHEMA}").get("policies", [])
        except Exception as e:  # noqa: BLE001
            print(f"Policy listing failed: {e}")
            policies = []
        return {**r, "policies": policies}
    r = sql_or_500(lambda: cached("governance", 20, build))
    editable = {persona_principal(k): k for k in PERSONAS if k != DEFAULT_PERSONA}
    tags: dict = {}
    for t in r["tags"]:
        label = f"{t['tag_name']}={t['tag_value']}" if t["tag_value"] else t["tag_name"]
        tags.setdefault(label, []).append(f"{t['table_name']}.{t['column_name']}")
    host = get_workspace_host().rstrip("/")
    return {
        "persona": current_persona(),
        "views": [{"persona": k, **{f: p[f] for f in ("label", "role", "identity")}, **(r[f"probe:{k}"] or {})} for k, p in PERSONAS.items()],
        "entitlements": [{**e, "persona": editable.get(e["principal"]), "editable": e["principal"] in editable} for e in r["entitlements"]],
        "policies": [
            {
                "name": p["name"], "comment": p.get("comment"), "type": "row_filter" if "row_filter" in p else "column_mask",
                "function": (p.get("row_filter") or p.get("column_mask") or {}).get("function_name"),
                "match": " AND ".join(m["condition"] for m in p.get("match_columns", [])), "to": p.get("to_principals", []),
            }
            for p in r["policies"]
        ],
        "tags": [{"tag": k, "columns": v} for k, v in tags.items()],
        "can_edit": is_access_admin(request),
        "catalog_url": f"{host}/explore/data/{UC_CATALOG}/{UC_SCHEMA}",
    }


class EntitlementIn(BaseModel):
    state_scope: list[str]
    pii_cleared: bool


@router.put("/governance/entitlements/{principal}")
def update_entitlement(principal: str, body: EntitlementIn, request: Request):
    if not is_access_admin(request):
        raise HTTPException(403, "Only access administrators can change entitlements")
    if principal not in {persona_principal(k) for k in PERSONAS if k != DEFAULT_PERSONA}:
        raise HTTPException(400, "Only demo persona entitlements can be edited from the app")
    scope = sorted({s.upper() for s in body.state_scope})
    if not scope or any(s != "*" and s not in STATE_SPECS for s in scope):
        raise HTTPException(400, "State scope must list known state codes or *")
    sql_or_500(lambda: run_sql(
        f"UPDATE {Q.T}.ref_data_entitlements SET state_scope = from_json(:scope, 'array<string>'), pii_cleared = (:pii = 'true') WHERE principal = :p",
        {"scope": json.dumps(scope), "pii": str(body.pii_cleared).lower(), "p": principal}, as_service=True,
    ))
    clear_cache()
    return {"ok": True}


class DraftIn(BaseModel):
    prompt: str


class BacktestIn(BaseModel):
    sql: str
    category: str = "fraud"


class RuleIn(BaseModel):
    prompt: str
    name: str
    category: str
    severity: str
    rationale: str = ""
    sql: str
    author_model: str | None = None


def _studio_call(fn):
    try:
        return fn()
    except rs.RuleError as e:
        raise HTTPException(422, str(e))
    except SqlError as e:
        raise HTTPException(422, f"Rule SQL did not run: {str(e)[:500]}")


@router.get("/rules/studio")
def rule_studio():
    rules = db.safe_query("SELECT * FROM custom_rules ORDER BY created_at DESC")
    stats = {s["rule_id"]: s for s in sql_or_500(lambda: cached("custom_stats", 10, lambda: run_sql(Q.CUSTOM_STATS)))}
    for r in rules:
        r["backtest"] = json.loads(r.pop("backtest_json") or "null")
        r["live"] = stats.get(r["rule_id"])
        r["snippet"] = rs.pipeline_snippet(r)
    return {"rules": rules, "examples": rs.EXAMPLES, "model": rs.ENDPOINT, "gates": rs.GATES, "tables": rs.SOURCE_TABLES}


@router.post("/rules/draft")
def draft_rule(body: DraftIn):
    prompt = body.prompt.strip()
    if len(prompt) < 8:
        raise HTTPException(400, "Describe the rule in a sentence")
    def go():
        rule = rs.draft(prompt)
        return {"rule": rule, "backtest": rs.backtest(rule["sql"], rule["category"])}
    return _studio_call(go)


@router.post("/rules/backtest")
def backtest_rule(body: BacktestIn):
    return _studio_call(lambda: rs.backtest(body.sql, body.category))


@router.post("/rules/custom")
def save_rule(body: RuleIn, request: Request):
    require_lakebase()
    if body.category not in ("fraud", "eligibility") or body.severity not in rs.SEVERITY_SCORE:
        raise HTTPException(400, "Unknown category or severity")
    sql = _studio_call(lambda: rs.clean_sql(body.sql))
    bt = _studio_call(lambda: rs.backtest(sql, body.category))
    ids = [r["rule_id"] for r in db.query("SELECT rule_id FROM custom_rules")]
    n = max([int(i.split("-")[1]) for i in ids if Q.RULE_ID.match(i)] + [0]) + 1
    rows = db.execute(
        """INSERT INTO custom_rules (rule_id, name, prompt, rationale, category, severity, sql_text, status, backtest_json, author_model, created_by, validated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CASE WHEN %s THEN now() END) RETURNING rule_id, status""",
        (f"CR-{n:02d}", body.name[:80], body.prompt, body.rationale, body.category, body.severity, sql, "validated" if bt["passed"] else "draft",
         json.dumps(bt, default=str), body.author_model, analyst(request), bt["passed"]),
    )
    return rows[0]


@router.post("/rules/custom/{rule_id}/promote")
def promote_rule(rule_id: str, request: Request):
    require_lakebase()
    rows = db.query("SELECT * FROM custom_rules WHERE rule_id = %s", (rule_id,))
    if not rows:
        raise HTTPException(404, "Unknown rule")
    rule = rows[0]
    if rule["status"] not in ("validated", "active"):
        raise HTTPException(409, "Rule must pass every validation gate before promotion")
    n = _studio_call(lambda: rs.apply(rule))
    db.execute("UPDATE custom_rules SET status = 'active', promoted_by = %s, promoted_at = now(), updated_at = now() WHERE rule_id = %s RETURNING rule_id", (analyst(request), rule_id))
    clear_cache()
    return {"rule_id": rule_id, "findings": n}


@router.post("/rules/custom/{rule_id}/retire")
def retire_rule(rule_id: str):
    require_lakebase()
    _studio_call(lambda: rs.retire(rule_id))
    db.execute("UPDATE custom_rules SET status = 'retired', updated_at = now() WHERE rule_id = %s RETURNING rule_id", (rule_id,))
    clear_cache()
    return {"ok": True}


PLATFORM_JOBS = {
    "orchestrate": ("ORCHESTRATE_JOB_ID", "DOL UI - rebuild demo"),
    "stream": ("STREAM_JOB_ID", "DOL UI - stream new state events"),
}
LAKEBASE_PROJECT = os.environ.get("LAKEBASE_PROJECT", "dol-ui")


def job_id(name: str) -> int | None:
    env, title = PLATFORM_JOBS[name]
    if os.environ.get(env):
        return int(os.environ[env])

    def find():
        for j in get_workspace_client().jobs.list(limit=100):
            if title in (j.settings.name or ""):
                return j.job_id
        return None
    return cached(f"job:{name}", 3600, find)


def _attempt(fn, default=None):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        print(f"Platform probe failed: {e}")
        return default


def _ts(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat() if ms else None


def job_status(name: str) -> dict:
    w = get_workspace_client()
    jid = job_id(name)
    if not jid:
        return {"available": False}
    out = {"available": True, "job_id": jid, "url": f"{get_workspace_host()}/jobs/{jid}"}
    job = _attempt(lambda: w.jobs.get(jid))
    if job:
        out["name"] = job.settings.name
        out["tasks"] = [t.task_key for t in job.settings.tasks or []]
        out["pipeline_id"] = next((t.pipeline_task.pipeline_id for t in job.settings.tasks or [] if t.pipeline_task), None)
    run = _attempt(lambda: next(iter(w.jobs.list_runs(job_id=jid, limit=1)), None))
    if run:
        st = run.state
        out["last_run"] = {
            "run_id": run.run_id, "url": run.run_page_url, "started": _ts(run.start_time), "ended": _ts(run.end_time),
            "life_cycle": st.life_cycle_state.value if st and st.life_cycle_state else None,
            "result": st.result_state.value if st and st.result_state else None,
        }
    return out


def pipeline_status(pipeline_id: str | None) -> dict:
    if not pipeline_id:
        return {"available": False}
    p = _attempt(lambda: get_workspace_client().pipelines.get(pipeline_id))
    out = {"available": True, "pipeline_id": pipeline_id, "url": f"{get_workspace_host()}/pipelines/{pipeline_id}"}
    if p:
        out["name"] = p.name
        out["state"] = p.state.value if p.state else None
        conf = (p.spec.configuration if p.spec else None) or {}
        out["share_catalogs"] = {k.removeprefix("share_catalog_").upper(): v for k, v in conf.items() if k.startswith("share_catalog_") and v}
        u = (p.latest_updates or [None])[0]
        if u:
            out["last_update"] = {"state": u.state.value if u.state else None, "at": u.creation_time}
    return out


CODE_FILES = {
    "rules": ("src/pipelines/rules.py", "Python rules", "Deterministic fraud and eligibility rules run inside the pipeline"),
    "ml": ("src/jobs/train_eval.py", "Model training and evaluation", "Feature build, gradient boosting, MLflow evaluation, UC registration, scoring"),
    "agent": ("src/genie/agent.py", "Genie Agent mode client", "Prompt, streaming Agents API call and verdict parsing, shared by job and app"),
    "agent_review": ("src/jobs/genie_review.py", "Agent batch review notebook", "Selects priority cases and records agent verdicts"),
    "rule_studio": ("server/rule_studio.py", "Rule studio", "Natural language to SQL, contract checks, backtest and promotion gates"),
}
GITHUB_REPO_URL = os.environ.get("GITHUB_REPO_URL", "").rstrip("/")


def bundle_files_root() -> str | None:
    def find():
        jid = job_id("orchestrate")
        if not jid:
            return None
        for t in get_workspace_client().jobs.get(jid).settings.tasks or []:
            f = t.spark_python_task.python_file if t.spark_python_task else ""
            if f.endswith("/src/jobs/train_eval.py"):
                return f.removesuffix("/src/jobs/train_eval.py")
        return None
    return cached("bundle_root", 3600, lambda: _attempt(find))


def code_links() -> dict:
    def build():
        w = get_workspace_client()
        host = get_workspace_host()
        root = bundle_files_root()
        out = {}
        for key, (rel, label, desc) in CODE_FILES.items():
            link = {"label": label, "description": desc, "path": rel, "github": f"{GITHUB_REPO_URL}/blob/main/{rel}" if GITHUB_REPO_URL else None, "url": None}
            for path in ([f"{root}/{rel}", f"{root}/{rel.removesuffix('.py')}"] if root else []):
                st = _attempt(lambda path=path: w.workspace.get_status(path))
                if st and st.object_id:
                    kind = "notebooks" if st.object_type and st.object_type.value == "NOTEBOOK" else "files"
                    link["url"] = f"{host}/editor/{kind}/{st.object_id}"
                    break
            link["url"] = link["url"] or link["github"]
            out[key] = link
        return out
    return cached("code_links", 3600, build)


def lakebase_branches() -> list[dict]:
    w = get_workspace_client()
    return [
        {"name": b.name.rsplit("/", 1)[-1], "state": b.status.current_state.value if b.status and b.status.current_state else None,
         "default": bool(b.status and b.status.default), "parent": (b.status.source_branch or "").rsplit("/", 1)[-1] if b.status else None}
        for b in w.postgres.list_branches(parent=f"projects/{LAKEBASE_PROJECT}")
    ]


def volume_files() -> list[str]:
    root = f"/Volumes/{UC_CATALOG}/{UC_SCHEMA}/state_drops/mi"
    return sorted(e.name for e in get_workspace_client().files.list_directory_contents(root) if (e.name or "").endswith(".csv"))


@router.get("/platform")
def platform():
    def build():
        r = parallel(
            stats=lambda: run_sql(Q.PLATFORM_STATS, as_service=True)[0],
            intel=lambda: run_sql(Q.PLATFORM_INTEL, as_service=True),
            governance=lambda: run_sql(Q.PLATFORM_GOVERNANCE, as_service=True)[0],
            model=lambda: _attempt(lambda: (run_sql(Q.MODEL_METRICS, as_service=True)), []),
            orchestrate=lambda: job_status("orchestrate"),
            stream=lambda: job_status("stream"),
            branches=lambda: _attempt(lakebase_branches, []),
            files=lambda: _attempt(volume_files, None),
            policies=lambda: _attempt(lambda: get_workspace_client().api_client.do("GET", f"/api/2.1/unity-catalog/policies/SCHEMA/{UC_CATALOG}.{UC_SCHEMA}").get("policies", []), []),
            federation=lambda: _attempt(lambda: run_sql(Q.PLATFORM_FEDERATION, as_service=True)[0], None),
        )
        pid = r["orchestrate"].get("pipeline_id") or r["stream"].get("pipeline_id")
        r["pipeline"] = pipeline_status(pid)
        return r
    r = sql_or_500(lambda: cached("platform", 20, build))
    host = get_workspace_host()
    explore = f"{host}/explore/data/{UC_CATALOG}/{UC_SCHEMA}"
    model = {m["metric"]: m["value"] for m in r["model"] or []}
    meta = (r["model"] or [{}])[0]
    model_name = meta.get("model_name") or f"{UC_CATALOG}.{UC_SCHEMA}.ui_fraud_ring_model"
    agent_id = config().get("genie_agent_id")
    mounted = r["pipeline"].get("share_catalogs", {})
    shares = []
    for code in SHARE_STATES:
        spec = STATE_SPECS[code]
        sh = spec["share"]
        catalog = mounted.get(code)
        shares.append({
            "state_code": code, "state_name": spec["name"], "agency": spec["agency"], "share": sh["name"], "mounted": bool(catalog),
            "source": f"{catalog}.uia.{sh['table']}" if catalog else f"{UC_CATALOG}.{sh['schema']}.{sh['table']}",
            "url": f"{host}/explore/data/{catalog}/uia/{sh['table']}" if catalog else f"{host}/explore/data/{UC_CATALOG}/{sh['schema']}/{sh['table']}",
        })
    transports: dict[str, list[str]] = {}
    for code, spec in STATE_SPECS.items():
        transports.setdefault(spec["transport"], []).append(code)
    return {
        **{k: r[k] for k in ("stats", "intel", "governance", "orchestrate", "stream", "pipeline", "branches", "files", "federation")},
        "shares": shares,
        "transports": transports,
        "code": _attempt(code_links, {}),
        "github": GITHUB_REPO_URL or None,
        "policies": len(r["policies"]),
        "model": {"name": model_name, "version": meta.get("model_version"), "auc": model.get("roc_auc"), "precision": model.get("precision"), "recall": model.get("recall"),
                  "url": f"{host}/explore/data/models/{model_name.replace('.', '/')}"},
        "links": {
            "workspace": host,
            "schema": explore,
            "landing": f"{explore}/bronze_claim_events",
            "bronze": f"{explore}/bronze_claim_events_stream",
            "silver": f"{explore}/silver_claim_events",
            "gold": f"{explore}/gold_claims",
            "lineage": f"{explore}/gold_applicant_profile?activeTab=lineage",
            "volume": f"{host}/explore/data/volumes/{UC_CATALOG}/{UC_SCHEMA}/state_drops",
            "findings": f"{explore}/gold_check_findings",
            "custom": f"{explore}/gold_custom_rule_findings",
            "agent": f"{host}/genie/rooms/{agent_id}" if agent_id else None,
            "app": f"{host}/apps/{os.environ.get('DATABRICKS_APP_NAME', 'dol-ui-claims')}",
            "lakebase": f"{host}/lakebase/projects/{LAKEBASE_PROJECT}",
            "policies": f"{host}/explore/data/{UC_CATALOG}/{UC_SCHEMA}?activeTab=policies",
            "entitlements": f"{explore}/ref_data_entitlements",
        },
        "catalog": f"{UC_CATALOG}.{UC_SCHEMA}",
        "rule_author": rs.ENDPOINT,
    }


@router.post("/platform/stream")
def trigger_stream(request: Request):
    if not is_access_admin(request):
        raise HTTPException(403, "Only access administrators can trigger platform jobs")
    jid = job_id("stream")
    if not jid:
        raise HTTPException(404, "Stream job not found")
    try:
        run = get_workspace_client().jobs.run_now(job_id=jid)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Could not start the stream job: {e}") from e
    clear_cache()
    return {"run_id": run.run_id, "url": f"{get_workspace_host()}/jobs/{jid}/runs/{run.run_id}"}


@router.get("/config")
def get_config():
    return {"config": config()}


@router.put("/config")
def put_config(body: dict):
    require_lakebase()
    for k, v in body.items():
        if k in DEFAULT_CONFIG:
            db.execute(
                "INSERT INTO app_config (key, value, updated_at) VALUES (%s, %s, now()) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
                (k, str(v)),
            )
    clear_cache()
    return {"config": config()}
