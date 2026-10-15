"""On-demand Genie Agent mode investigations run in background threads and are polled by the UI."""

import json
import threading
import uuid
from datetime import datetime, timezone

from server import db
from server.config import get_workspace_client, get_workspace_host
from src.genie.agent import build_prompt, run_agent

_runs: dict[str, dict] = {}
_lock = threading.Lock()


def _persist(sql, params):
    try:
        db.execute(sql, params)
    except Exception as e:  # noqa: BLE001
        print(f"Lakebase write failed: {e}")


def start(agent_id: str, applicant_key: str, name: str, states: list[str], requested_by: str) -> str:
    run_id = uuid.uuid4().hex
    prompt = build_prompt(applicant_key, name, states)
    with _lock:
        _runs[run_id] = {"run_id": run_id, "status": "running", "steps": [], "result": None, "error": None, "applicant_key": applicant_key}
    _persist(
        "INSERT INTO investigation_runs (id, applicant_key, prompt, status, requested_by) VALUES (%s, %s, %s, 'running', %s)",
        (run_id, applicant_key, prompt, requested_by),
    )
    threading.Thread(target=_work, args=(run_id, agent_id, prompt), daemon=True).start()
    return run_id


def _work(run_id, agent_id, prompt):
    def on_step(step):
        with _lock:
            _runs[run_id]["steps"].append(step)

    try:
        w = get_workspace_client()
        res = run_agent(get_workspace_host(), w.config.authenticate(), agent_id, prompt, on_step=on_step)
        res["completed_at"] = datetime.now(timezone.utc).isoformat()
        with _lock:
            _runs[run_id].update(status="completed", result=res)
        _persist(
            """UPDATE investigation_runs SET status = 'completed', conversation_id = %s, report = %s, verdict = %s, confidence = %s,
               summary = %s, steps_json = %s, sql_count = %s, completed_at = now() WHERE id = %s""",
            (res["conversation_id"], res["report"], res["verdict"], res["confidence"], res["summary"], json.dumps(res["steps"]), res["sql_count"], run_id),
        )
    except Exception as e:  # noqa: BLE001
        with _lock:
            _runs[run_id].update(status="failed", error=str(e)[:500])
        _persist("UPDATE investigation_runs SET status = 'failed', error = %s, completed_at = now() WHERE id = %s", (str(e)[:500], run_id))


def get(run_id: str) -> dict | None:
    with _lock:
        r = _runs.get(run_id)
        return json.loads(json.dumps(r, default=str)) if r else None
