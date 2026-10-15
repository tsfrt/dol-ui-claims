"""Genie Agents Agent mode client shared by the batch review job and the analyst app."""

import json
import re

import requests

VERDICTS = ("FRAUD", "INELIGIBLE", "ELIGIBLE", "NEEDS_REVIEW")
VERDICT_RE = re.compile(r"VERDICT:\s*\**\s*(FRAUD|INELIGIBLE|ELIGIBLE|NEEDS_REVIEW)", re.I)
CONFIDENCE_RE = re.compile(r"CONFIDENCE:\s*\**\s*(HIGH|MEDIUM|LOW)", re.I)
SUMMARY_RE = re.compile(r"SUMMARY:\s*\**\s*(.+)", re.I)


class AgentError(RuntimeError):
    pass


def build_prompt(applicant_key, name=None, states=None):
    where = f" with claims in {', '.join(states)}" if states else ""
    return (
        f"Investigate unemployment insurance claimant applicant_key '{applicant_key}'{where}.\n"
        "Work through: (1) federal intel matches (SSA death master, BOP, NDNH wages, SSA identity, Treasury Do Not Pay); "
        "(2) bank accounts, devices, and IP subnets shared with other claimants in gold_identity_links, and whether those "
        "linked claimants are themselves flagged; (3) overlapping paid weeks across states; (4) eligibility: base-period wages "
        "vs the state minimum, separation reason, work search, and weeks paid vs maximum duration; (5) the rules findings and ML score.\n"
        "Write a concise investigator report (under 220 words) citing the specific evidence and dollars at risk. "
        "The report is shared with analysts who are not PII-cleared: refer to people only as 'the claimant' or 'linked claimant' "
        "with their state claim IDs, and never include names, SSNs, dates of birth, bank tokens, device IDs, or IP addresses. "
        "End with exactly three lines:\n"
        "VERDICT: <FRAUD|INELIGIBLE|ELIGIBLE|NEEDS_REVIEW>\nCONFIDENCE: <HIGH|MEDIUM|LOW>\nSUMMARY: <one sentence>"
    )


def _step(item):
    kind = item.get("type")
    if kind == "reasoning":
        text = " ".join(c.get("text", "") for c in item.get("content", []) if c.get("type") == "reasoning_text").strip()
        return {"kind": "reasoning", "text": text[:600]} if text else None
    if kind == "function_call":
        try:
            a = json.loads(item.get("arguments") or "{}")
        except ValueError:
            a = {}
        return {"kind": "sql", "title": a.get("title") or item.get("name"), "sql": a.get("sql", "")}
    if kind == "function_call_output":
        out = item.get("output") or ""
        return {"kind": "result", "text": out[:1500]}
    if kind == "message" and item.get("role") == "assistant":
        return {"kind": "report"}
    return None


def parse_response(response, conversation_id=None):
    steps, report_parts = [], []
    for item in (response or {}).get("output", []):
        s = _step(item)
        if s and s["kind"] != "report":
            steps.append(s)
        if item.get("type") == "message" and item.get("role") == "assistant":
            for c in item.get("content", []):
                if c.get("type") == "output_text" and c.get("text"):
                    text = re.sub(r"\s*\[\d+\]\([^)]*\)", "", c["text"])
                    report_parts.append(re.sub(r"\s*\\?\[\\?\]", "", text))
    report = "\n\n".join(report_parts).strip()
    verdict = VERDICT_RE.search(report)
    confidence = CONFIDENCE_RE.search(report)
    summary = SUMMARY_RE.search(report)
    body = re.split(r"\n\s*\**VERDICT:", report, flags=re.I)[0].strip()
    return {
        "conversation_id": conversation_id or (response or {}).get("conversation_id"),
        "verdict": verdict.group(1).upper() if verdict else "NEEDS_REVIEW",
        "confidence": confidence.group(1).upper() if confidence else "LOW",
        "summary": summary.group(1).strip().strip("*") if summary else body[:240],
        "report": body,
        "steps": steps,
        "sql_count": sum(1 for s in steps if s["kind"] == "sql"),
    }


def run_agent(host, headers, agent_id, prompt, on_step=None, timeout=900):
    url = f"{host.rstrip('/')}/api/2.0/genie/agents/{agent_id}/responses"
    body = {"input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": prompt}]}]}
    hdrs = {**headers, "Accept": "text/event-stream", "Content-Type": "application/json"}
    conversation_id, final = None, None
    with requests.post(url, headers=hdrs, json=body, stream=True, timeout=(30, timeout)) as r:
        if r.status_code != 200:
            raise AgentError(f"HTTP {r.status_code}: {r.text[:400]}")
        r.encoding = "utf-8"
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except ValueError:
                continue
            t = ev.get("type")
            if t == "response.created":
                conversation_id = ev.get("response", {}).get("conversation_id")
            elif t == "response.output_item.done" and on_step:
                s = _step(ev.get("item", {}))
                if s:
                    on_step(s)
            elif t == "response.completed":
                final = ev.get("response")
                break
            elif t == "response.failed":
                raise AgentError(json.dumps(ev.get("response", {}).get("error"))[:400])
    if final is None:
        raise AgentError("Agent stream ended without a completed response")
    return parse_response(final, conversation_id)
