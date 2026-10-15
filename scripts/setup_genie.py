"""Create or update the DOL UI integrity Genie agent and print its ID.

Usage: python scripts/setup_genie.py [--space-id ID]
Requires the Databricks CLI profile in DATABRICKS_CONFIG_PROFILE.
"""

import argparse
import json
import subprocess
import uuid

CLI = "/opt/homebrew/bin/databricks"
NS = "lanl.dol_ui"
WAREHOUSE = "688f49c732cf9083"
TITLE = "DOL UI Claims Integrity Investigator"

TABLES = {
    "gold_applicant_profile": "One row per claimant resolved across states by SSN hash (applicant_key = ssn_hash). Names, DOB, states, total paid, latest status.",
    "gold_claims": "One row per state claim: status, weeks paid, total paid, weekly benefit, employer, separation reason, bank token, device, IP subnet, zero work search weeks.",
    "gold_claim_weeks": "Week-by-week status and payment for every claim, including work search contacts.",
    "gold_check_findings": "Rules engine findings: rule_id, rule_name, category (fraud or eligibility), severity, evidence, amount_at_risk per claim.",
    "gold_rule_catalog": "Descriptions of each Python rule and its federal intel source.",
    "gold_ml_scores": "Behavioral ML fraud score (0-1) for every claimant with risk band, top drivers, and the model features.",
    "gold_identity_links": "Bank accounts, devices, and IP subnets shared by more than one claimant, with the list of applicant_keys. Large shared clusters indicate fraud rings.",
    "gold_interstate_pairs": "State pairs where the same claimant was paid for overlapping weeks.",
    "gold_state_summary": "Per-state operations summary and program parameters.",
    "intel_ssa_death_master": "SSA Death Master File analog keyed by ssn_hash.",
    "intel_bop_inmates": "Bureau of Prisons custody records keyed by ssn_hash; null release_date means still in custody.",
    "intel_ndnh_quarterly_wages": "HHS National Directory of New Hires quarterly wages keyed by ssn_hash, with employer and quarter_start.",
    "intel_ssa_identity": "SSA identity verification: the name and DOB SSA has on file for each ssn_hash.",
    "intel_treasury_dnp": "Treasury Do Not Pay list matches keyed by ssn_hash.",
    "ref_state_programs": "State UI program parameters: max weekly benefit, minimum base-period wages, maximum weeks.",
}

INSTRUCTIONS = """You are an unemployment insurance (UI) integrity investigator for the U.S. Department of Labor reviewing claims from 14 state workforce agencies.
- applicant_key equals ssn_hash; join every intel table on ssn_hash = applicant_key.
- Fraud signals: deceased claimant (filed after SSA date of death), incarcerated while certifying, NDNH wages from a different employer during paid weeks, overlapping paid weeks in two states, SSA name/DOB mismatch, Treasury Do Not Pay listing, and membership in a fraud ring (shared bank_account, device, or ip_subnet clusters in gold_identity_links with 3+ claimants, especially when the cited employer has single-quarter wage history).
- Eligibility issues: base-period wages below ref_state_programs.min_base_wages, separation_reason voluntary_quit or misconduct, 3+ paid weeks with zero work search contacts, weeks_paid above max_weeks.
- When investigating a claimant, always check identity links: explode gold_identity_links.applicant_keys and look at the linked claimants' findings and ML scores.
- Report dollar amounts at risk from total_paid / amount_at_risk. Be concise and evidence-based; never invent data."""

SAMPLE_QUESTIONS = [
    "Which fraud rings share a bank account across multiple states, and how much have they been paid?",
    "Which states have the highest improper payment amounts at risk?",
    "Show claimants paid by two states for the same weeks",
    "Which claimants did the ML model flag that no rule caught?",
]


def hexid():
    return uuid.uuid4().hex


def serialized():
    return json.dumps({
        "version": 2,
        "config": {"sample_questions": sorted([{"id": hexid(), "question": [q]} for q in SAMPLE_QUESTIONS], key=lambda x: x["id"])},
        "data_sources": {"tables": sorted([{"identifier": f"{NS}.{t}", "description": [d]} for t, d in TABLES.items()], key=lambda x: x["identifier"])},
        "instructions": {"text_instructions": [{"id": hexid(), "content": [INSTRUCTIONS]}]},
    })


def api(method, path, body):
    out = subprocess.run([CLI, "api", method, path, "--json", json.dumps(body)], capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(out.stderr or out.stdout)
    return json.loads(out.stdout or "{}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--space-id")
    a = ap.parse_args()
    body = {"title": TITLE, "description": "Investigates UI claimants across state claims, federal intel, rules findings, ML scores, and identity links.", "warehouse_id": WAREHOUSE, "serialized_space": serialized()}
    if a.space_id:
        res = api("patch", f"/api/2.0/genie/spaces/{a.space_id}", body)
    else:
        res = api("post", "/api/2.0/genie/spaces", body)
    print(res.get("space_id"))
