"""Synthetic UI claimants, state claim events, and federal intel analogs.

Every applicant follows a "story". Fraud and ineligibility stories plant the
signals each detection technique is designed to find:

  rules  -> deterministic intel matches and eligibility law (SSA DMF, BOP, NDNH,
            SSA identity, Treasury DNP, monetary, separation, work search, exhaustion)
  ml     -> behavioral fraud rings (shared bank tokens, devices, IPs, shell
            employers with single-quarter wages) that no single rule can see
  agent  -> the Genie agent investigates ambiguous and high-impact cases end to end
"""

import hashlib
import json
import random
from datetime import date, datetime, timedelta

from faker import Faker

from state_specs import COUNTIES, STATE_SPECS, STATES

TODAY = date.today()

FRAUD_STORIES = {"deceased", "incarcerated", "working_while_claiming", "interstate_duplicate", "identity_theft", "treasury_dnp", "fraud_ring"}
INELIGIBLE_STORIES = {"monetary_ineligible", "disqualifying_separation", "work_search", "exhausted_overpaid"}

STORY_WEIGHTS = [
    ("clean", 0.72),
    ("deceased", 0.02),
    ("incarcerated", 0.02),
    ("working_while_claiming", 0.03),
    ("interstate_duplicate", 0.03),
    ("identity_theft", 0.025),
    ("treasury_dnp", 0.015),
    ("fraud_ring", 0.05),
    ("monetary_ineligible", 0.025),
    ("disqualifying_separation", 0.03),
    ("work_search", 0.02),
    ("exhausted_overpaid", 0.015),
]

STATE_WEIGHTS = {"CA": 0.19, "TX": 0.14, "NY": 0.12, "FL": 0.10, "PA": 0.09, "IL": 0.09, "WA": 0.07, "MA": 0.07, "GA": 0.07, "NJ": 0.06, "MI": 0.07, "OH": 0.07, "CO": 0.05, "NC": 0.06}

LAYOFF_EMPLOYERS = [
    "Northwind Logistics", "Contoso Retail Group", "Fabrikam Manufacturing", "Tailspin Airlines", "Adventure Works Hospitality",
    "Litware Software", "Proseware Health", "Wide World Importers", "Coho Winery", "Alpine Ski House", "Blue Yonder Freight",
    "Lucerne Publishing", "Margie's Travel", "Trey Research", "Woodgrove Bank",
]


def sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def monday(d):
    return d - timedelta(days=d.weekday())


def quarter_label(d):
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def quarter_start(d):
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def prev_quarters(d, n):
    qs = []
    q = quarter_start(d)
    for _ in range(n):
        q = quarter_start(q - timedelta(days=1))
        qs.append(q)
    return list(reversed(qs))


def fmt_ssn(ssn, style):
    return f"{ssn[:3]}-{ssn[3:5]}-{ssn[5:]}" if style == "dashed" else ssn


def fmt_date(d, style):
    if style == "us":
        return d.strftime("%m/%d/%Y")
    if style == "mmddyyyy":
        return d.strftime("%m%d%Y")
    if style == "yyyyww":
        y, w, _ = d.isocalendar()
        return f"{y}{w:02d}"
    return d.isoformat()


def fmt_amount(x, unit):
    if x is None:
        return None
    if unit == "cents":
        return int(round(x * 100))
    if unit == "currency_string":
        return f"${x:,.2f}"
    return round(float(x), 2)


def set_path(obj, path, value):
    keys = path.lstrip("$.").split(".")
    for k in keys[:-1]:
        obj = obj.setdefault(k, {})
    obj[keys[-1]] = value


def render_payload(state, ev):
    spec = STATE_SPECS[state]
    f = spec["fields"]
    week = ev["week"]
    if spec["week_anchor"] == "end":
        week = week + timedelta(days=6)
    status = spec["status_codes"][ev["status"]]
    if state == "TX":
        status = int(status)
    values = {
        "status": status,
        "ssn": fmt_ssn(ev["ssn"], spec["ssn_format"]),
        "first_name": ev["first_name"],
        "last_name": ev["last_name"],
        "dob": fmt_date(ev["dob"], spec["date_format"]),
        "claim_id": ev["claim_id"],
        "week": fmt_date(week, spec["week_format"]),
        "wba": fmt_amount(ev.get("wba"), spec["amount_unit"]),
        "paid": fmt_amount(ev.get("paid"), spec["amount_unit"]),
        "employer": ev.get("employer"),
        "county": ev.get("county"),
        "separation": spec["separation_codes"][ev["separation"]] if ev.get("separation") else None,
        "work_search": ev.get("work_search"),
        "bank_token": ev.get("bank_token"),
        "device_id": ev.get("device_id"),
        "ip_address": ev.get("ip_address"),
    }
    payload = {}
    for k, v in values.items():
        if v is not None:
            set_path(payload, f[k], v)
    return payload


class Generator:
    def __init__(self, n_applicants, seed):
        self.n = n_applicants
        self.rng = random.Random(seed)
        self.fake = Faker("en_US")
        Faker.seed(seed)
        self.used_ssn = set()
        self.applicants = []
        self.events = []
        self.wages = []
        self.deaths = []
        self.inmates = []
        self.identity = []
        self.dnp = []
        self.claim_seq = 0

    def ssn(self):
        while True:
            a = self.rng.randint(1, 899)
            if a == 666:
                continue
            s = f"{a:03d}{self.rng.randint(1, 99):02d}{self.rng.randint(1, 9999):04d}"
            if s not in self.used_ssn:
                self.used_ssn.add(s)
                return s

    def token(self, prefix):
        return f"{prefix}_{self.rng.getrandbits(48):012x}"

    def ip(self, prefix=None):
        if prefix:
            return f"{prefix}.{self.rng.randint(2, 254)}"
        return f"{self.rng.choice([24, 47, 66, 71, 98, 104, 172, 174])}.{self.rng.randint(1, 254)}.{self.rng.randint(1, 254)}.{self.rng.randint(2, 254)}"

    def pick_state(self, exclude=()):
        choices = [s for s in STATES if s not in exclude]
        weights = [STATE_WEIGHTS[s] for s in choices]
        return self.rng.choices(choices, weights=weights)[0]

    def person(self, state):
        first = self.fake.first_name()
        last = self.fake.last_name()
        dob = date(1958, 1, 1) + timedelta(days=self.rng.randint(0, 365 * 45))
        return {
            "ssn": self.ssn(),
            "first_name": first,
            "last_name": last,
            "dob": dob,
            "home_state": state,
            "county": self.rng.choice(COUNTIES[state]),
            "bank_token": self.token("dd"),
            "device_id": self.token("dv"),
            "ip_address": self.ip(),
            "employer": self.rng.choice(LAYOFF_EMPLOYERS) if self.rng.random() < 0.45 else self.fake.company(),
            "separation": "lack_of_work",
        }

    def wba_for(self, state, base_total, high_q):
        spec = STATE_SPECS[state]
        return round(min(spec["max_wba"], max(50.0, high_q / 26.0)), 2)

    def add_base_wages(self, p, claim_start, quarters=4, total=None, employer=None, single_quarter=False):
        qs = prev_quarters(claim_start, 5)[:4]
        amounts = []
        if single_quarter:
            amounts = [0, 0, 0, total]
        else:
            total = total or self.rng.uniform(14000, 72000)
            parts = [self.rng.uniform(0.8, 1.2) for _ in qs]
            amounts = [round(total * x / sum(parts), 2) for x in parts]
        for q, amt in zip(qs, amounts):
            if amt > 0:
                self.wages.append({
                    "ssn_hash": sha(p["ssn"]),
                    "quarter": quarter_label(q),
                    "quarter_start": q,
                    "employer_name": employer or p["employer"],
                    "employer_fein": f"{int(sha(employer or p['employer'])[:8], 16) % 10**9:09d}",
                    "reporting_state": p["home_state"],
                    "wages": amt,
                })
        return sum(amounts), max(amounts)

    def claim(self, p, state, start, n_weeks, outcome="paid", wba=None, work_search=None, separation=None, extra_paid_after_exhaust=0, filing=None):
        self.claim_seq += 1
        claim_id = f"{state}{start.strftime('%y%m')}{self.claim_seq:07d}"
        filing = filing or {}
        base = {
            "state": state,
            "claim_id": claim_id,
            "ssn": p["ssn"],
            "first_name": p["first_name"],
            "last_name": p["last_name"],
            "dob": p["dob"],
            "wba": wba,
        }
        seq = 0
        evs = []

        def emit(status, week, ts, **kw):
            nonlocal seq
            seq += 1
            ev = dict(base, status=status, week=week, ts=ts, event_id=f"{state}-{claim_id}-{seq:03d}")
            ev.update(kw)
            evs.append(ev)

        filed_ts = datetime.combine(start, datetime.min.time()) + timedelta(hours=self.rng.randint(6, 23), minutes=self.rng.randint(0, 59))
        emit("filed", start, filed_ts,
             employer=filing.get("employer", p["employer"]),
             county=filing.get("county", p["county"] if state == p["home_state"] else self.rng.choice(COUNTIES[state])),
             separation=separation or p["separation"],
             bank_token=filing.get("bank_token", p["bank_token"]),
             device_id=filing.get("device_id", p["device_id"]),
             ip_address=filing.get("ip_address", p["ip_address"]))
        emit("pending", start, filed_ts + timedelta(days=self.rng.randint(1, 4), hours=self.rng.randint(0, 8)))

        if outcome == "denied":
            emit("denied", start, filed_ts + timedelta(days=self.rng.randint(8, 20)))
            self.events.extend(evs)
            return claim_id
        if outcome == "appealed":
            emit("denied", start, filed_ts + timedelta(days=9))
            emit("appealed", start, filed_ts + timedelta(days=16))

        max_weeks = STATE_SPECS[state]["max_weeks"]
        paid_weeks = min(n_weeks, max_weeks) if outcome != "exhausted" else max_weeks
        last_week = start
        for i in range(paid_weeks):
            wk = start + timedelta(weeks=i + 1)
            if wk + timedelta(days=7) > TODAY:
                break
            ws = work_search[i] if work_search and i < len(work_search) else self.rng.randint(3, 6)
            emit("paid", wk, datetime.combine(wk + timedelta(days=6), datetime.min.time()) + timedelta(hours=self.rng.randint(7, 22)), paid=wba, work_search=ws)
            last_week = wk
        if outcome == "exhausted" and last_week + timedelta(days=8) <= TODAY:
            emit("exhausted", last_week, datetime.combine(last_week + timedelta(days=7), datetime.min.time()) + timedelta(hours=9))
            for j in range(extra_paid_after_exhaust):
                wk = last_week + timedelta(weeks=j + 1)
                if wk + timedelta(days=7) > TODAY:
                    break
                emit("paid", wk, datetime.combine(wk + timedelta(days=6), datetime.min.time()) + timedelta(hours=14), paid=wba, work_search=self.rng.randint(3, 5))
        self.events.extend(evs)
        return claim_id

    def random_start(self, min_weeks_ago=3, max_weeks_ago=30):
        return monday(TODAY - timedelta(weeks=self.rng.randint(min_weeks_ago, max_weeks_ago)))

    def register(self, p, story, ring_id=None):
        cat = "fraud" if story in FRAUD_STORIES else "eligibility" if story in INELIGIBLE_STORIES else "clean"
        self.identity.append({
            "ssn_hash": sha(p["ssn"]),
            "first_name": p.get("ssa_first", p["first_name"]),
            "last_name": p.get("ssa_last", p["last_name"]),
            "dob": p.get("ssa_dob", p["dob"]),
            "verification_code": "MATCH" if "ssa_first" not in p else "NAME_DOB_MISMATCH",
        })
        self.applicants.append({
            "applicant_key": sha(p["ssn"]),
            "ssn_hash": sha(p["ssn"]),
            "first_name": p["first_name"],
            "last_name": p["last_name"],
            "dob": p["dob"],
            "home_state": p["home_state"],
            "story": story,
            "category": cat,
            "ring_id": ring_id,
            "label_fraud": int(cat == "fraud"),
            "label_ineligible": int(cat == "eligibility"),
        })

    def standard(self, p, story):
        state = p["home_state"]
        start = self.random_start()
        base_total, high_q = self.add_base_wages(p, start)
        wba = self.wba_for(state, base_total, high_q)
        weeks = self.rng.randint(3, 22)

        if story == "clean":
            r = self.rng.random()
            if r < 0.08:
                self.claim(p, state, start, 0, outcome="denied", wba=wba)
            elif r < 0.12:
                self.claim(p, state, start, weeks, outcome="appealed", wba=wba)
            elif r < 0.15:
                start = self.random_start(STATE_SPECS[state]["max_weeks"] + 2, 34)
                self.claim(p, state, start, 0, outcome="exhausted", wba=wba)
            elif r < 0.19:
                first = self.random_start(24, 34)
                self.claim(p, state, first, self.rng.randint(3, 6), wba=wba)
                mover_state = self.pick_state(exclude=(state,))
                self.claim(p, mover_state, first + timedelta(weeks=12), self.rng.randint(2, 8), wba=self.wba_for(mover_state, base_total, high_q))
            elif r < 0.22:
                self.inmates.append({
                    "ssn_hash": sha(p["ssn"]),
                    "facility": self.rng.choice(["FCI Dublin", "FCI Englewood", "USP Atlanta", "FCI Fort Dix", "FCI Danbury"]),
                    "admit_date": start - timedelta(days=self.rng.randint(1500, 3000)),
                    "release_date": start - timedelta(days=self.rng.randint(200, 900)),
                    "source": "BOP SENTRY",
                })
                self.claim(p, state, start, weeks, wba=wba)
            else:
                self.claim(p, state, start, weeks, wba=wba)
        elif story == "deceased":
            self.deaths.append({"ssn_hash": sha(p["ssn"]), "date_of_death": start - timedelta(days=self.rng.randint(90, 900)), "source": "SSA Death Master File"})
            self.claim(p, state, start, weeks, wba=wba)
        elif story == "incarcerated":
            self.inmates.append({
                "ssn_hash": sha(p["ssn"]),
                "facility": self.rng.choice(["FCI Terminal Island", "FCI Seagoville", "MDC Brooklyn", "FCI Miami", "FCI Pekin"]),
                "admit_date": start - timedelta(days=self.rng.randint(30, 700)),
                "release_date": None,
                "source": "BOP SENTRY",
            })
            self.claim(p, state, start, weeks, wba=wba)
        elif story == "working_while_claiming":
            weeks = max(weeks, 8)
            self.claim(p, state, start, weeks, wba=wba)
            new_emp = self.fake.company()
            q = quarter_start(start + timedelta(weeks=3))
            for qq in {q, quarter_start(start + timedelta(weeks=weeks))}:
                if qq <= TODAY:
                    self.wages.append({
                        "ssn_hash": sha(p["ssn"]), "quarter": quarter_label(qq), "quarter_start": qq,
                        "employer_name": new_emp, "employer_fein": f"{self.rng.randint(10**8, 10**9 - 1)}",
                        "reporting_state": state, "wages": round(self.rng.uniform(6500, 16000), 2),
                    })
        elif story == "interstate_duplicate":
            other = self.pick_state(exclude=(state,))
            self.claim(p, state, start, max(weeks, 6), wba=wba)
            self.claim(p, other, start + timedelta(weeks=self.rng.randint(0, 2)), max(weeks, 6), wba=self.wba_for(other, base_total, high_q),
                       filing={"device_id": self.token("dv"), "ip_address": self.ip()})
            if self.rng.random() < 0.35:
                third = self.pick_state(exclude=(state, other))
                self.claim(p, third, start + timedelta(weeks=self.rng.randint(0, 2)), max(weeks, 6), wba=self.wba_for(third, base_total, high_q),
                           filing={"device_id": self.token("dv"), "ip_address": self.ip()})
        elif story == "identity_theft":
            self.claim(p, state, start, weeks, wba=wba)
        elif story == "treasury_dnp":
            self.dnp.append({
                "ssn_hash": sha(p["ssn"]),
                "list_name": self.rng.choice(["OIG UI Fraud Referral", "SAM Exclusion", "Treasury Offset Program"]),
                "reason": self.rng.choice(["Prior UI fraud conviction", "Debarred federal contractor", "Delinquent federal debt referral"]),
                "listed_date": start - timedelta(days=self.rng.randint(60, 1200)),
            })
            self.claim(p, state, start, weeks, wba=wba)
        elif story == "disqualifying_separation":
            self.claim(p, state, start, weeks, wba=wba, separation=self.rng.choice(["voluntary_quit", "misconduct"]))
        elif story == "work_search":
            weeks = max(weeks, 6)
            ws = [self.rng.randint(3, 5) if i < 2 else 0 for i in range(weeks)]
            self.claim(p, state, start, weeks, wba=wba, work_search=ws)
        elif story == "exhausted_overpaid":
            start = self.random_start(STATE_SPECS[state]["max_weeks"] + 5, 34)
            self.claim(p, state, start, 0, outcome="exhausted", wba=wba, extra_paid_after_exhaust=self.rng.randint(2, 4))

    def monetary_ineligible(self, p):
        state = p["home_state"]
        start = self.random_start()
        minimum = STATE_SPECS[state]["min_base_wages"]
        total = round(self.rng.uniform(0.25, 0.8) * minimum, 2)
        base_total, high_q = self.add_base_wages(p, start, total=total)
        self.claim(p, state, start, self.rng.randint(4, 14), wba=round(self.rng.uniform(120, 260), 2))

    def rings(self, n_members):
        n_rings = max(2, n_members // 8)
        out = []
        for r in range(n_rings):
            ring_id = f"RING-{r + 1:03d}"
            shell = f"{self.fake.last_name()} {self.rng.choice(['Staffing', 'Logistics', 'Consulting', 'Solutions'])} LLC"
            bank = self.token("dd")
            device = self.token("dv")
            subnet = f"{self.rng.choice([45, 91, 185, 193])}.{self.rng.randint(1, 254)}.{self.rng.randint(1, 254)}"
            states = self.rng.sample(STATES, self.rng.randint(2, 4))
            launch = self.random_start(4, 20)
            size = self.rng.randint(6, 11)
            for i in range(size):
                state = states[i % len(states)]
                p = self.person(state)
                p["employer"] = shell
                filing = {
                    "employer": shell,
                    "bank_token": bank if self.rng.random() < 0.8 else self.token("dd"),
                    "device_id": device if self.rng.random() < 0.7 else self.token("dv"),
                    "ip_address": self.ip(subnet) if self.rng.random() < 0.85 else self.ip(),
                }
                start = launch + timedelta(days=self.rng.randint(0, 9))
                start = monday(start)
                high = round(self.rng.uniform(15000, 26000), 2)
                self.add_base_wages(p, start, total=high, employer=shell, single_quarter=True)
                wba = STATE_SPECS[state]["max_wba"]
                self.claim(p, state, start, self.rng.randint(5, 16), wba=float(wba), filing=filing)
                self.register(p, "fraud_ring", ring_id)
                out.append(p)
        return out

    def run(self):
        counts = {s: int(round(self.n * w)) for s, w in STORY_WEIGHTS}
        crews = [self.token("dv") for _ in range(max(1, counts["identity_theft"] // 4))]
        household = None
        for story, k in counts.items():
            if story == "fraud_ring":
                self.rings(k)
                continue
            for _ in range(k):
                state = self.pick_state()
                p = self.person(state)
                if story == "clean" and self.rng.random() < 0.16:
                    if household and household["home_state"] == state:
                        p["bank_token"], p["device_id"], p["ip_address"] = household["bank_token"], household["device_id"], household["ip_address"]
                        p["last_name"] = household["last_name"]
                        household = None
                    else:
                        household = p
                if story == "identity_theft":
                    p["ssa_first"] = self.fake.first_name()
                    p["ssa_last"] = self.fake.last_name()
                    p["ssa_dob"] = p["dob"] - timedelta(days=self.rng.randint(400, 9000))
                    p["device_id"] = self.rng.choice(crews)
                    p["bank_token"] = self.token("pp")
                if story == "monetary_ineligible":
                    self.monetary_ineligible(p)
                else:
                    self.standard(p, story)
                self.register(p, story)
        return self


def generate(n_applicants=4000, seed=1937):
    g = Generator(n_applicants, seed).run()
    events = []
    for ev in g.events:
        state = ev["state"]
        events.append({
            "event_id": ev["event_id"],
            "state_code": state,
            "agency": STATE_SPECS[state]["agency"],
            "event_ts_unix_us": int(ev["ts"].timestamp() * 1_000_000),
            "payload": json.dumps(render_payload(state, ev), separators=(",", ":")),
        })
    events.sort(key=lambda e: e["event_ts_unix_us"])
    laus = []
    rng = random.Random(7)
    for st, counties in COUNTIES.items():
        for c in counties:
            laus.append({"state_code": st, "county": c, "period": "2026-09", "unemployment_rate": round(rng.uniform(2.8, 7.4), 1), "labor_force": rng.randint(150_000, 5_200_000)})
    programs = [{
        "state_code": s, "state_name": v["name"], "agency": v["agency"], "system": v["system"], "max_wba": float(v["max_wba"]),
        "min_base_wages": float(v["min_base_wages"]), "max_weeks": v["max_weeks"], "work_search_required": v["work_search_required"],
    } for s, v in STATE_SPECS.items()]
    return {
        "applicants": g.applicants,
        "events": events,
        "intel_ndnh_quarterly_wages": g.wages,
        "intel_ssa_death_master": g.deaths,
        "intel_bop_inmates": g.inmates,
        "intel_ssa_identity": g.identity,
        "intel_treasury_dnp": g.dnp,
        "intel_bls_laus": laus,
        "ref_state_programs": programs,
    }
