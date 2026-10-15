import contextvars
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from databricks.sdk.service.sql import StatementParameterListItem, StatementState

from server.config import PersonaUnavailable, current_persona, get_workspace_client, persona_client

WAREHOUSE_ID = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")
_pool = ThreadPoolExecutor(max_workers=8)
_cache: dict = {}
_lock = threading.Lock()


class SqlError(RuntimeError):
    pass


def _convert(value, type_name):
    if value is None:
        return None
    t = (type_name or "STRING").upper()
    if t in ("INT", "LONG", "SHORT", "BYTE"):
        return int(value)
    if t in ("DOUBLE", "FLOAT", "DECIMAL"):
        return float(value)
    if t == "BOOLEAN":
        return value in (True, "true", "True", "1")
    if t in ("ARRAY", "MAP", "STRUCT"):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value
    return value


def run_sql(sql: str, params: dict | None = None, timeout_s: int = 90, as_service: bool = False) -> list[dict]:
    """Runs as the selected persona so Unity Catalog row filters and masks apply to that identity."""
    if not WAREHOUSE_ID:
        raise SqlError("DATABRICKS_WAREHOUSE_ID is not set")
    try:
        w = get_workspace_client() if as_service else persona_client(current_persona())
    except PersonaUnavailable as e:
        raise SqlError(str(e)) from e
    plist = [StatementParameterListItem(name=k, value=None if v is None else str(v), type="STRING") for k, v in (params or {}).items()]
    stmt = w.statement_execution.execute_statement(warehouse_id=WAREHOUSE_ID, statement=sql, parameters=plist or None, wait_timeout="30s")
    start = time.time()
    while stmt.status and stmt.status.state in (StatementState.PENDING, StatementState.RUNNING):
        if time.time() - start > timeout_s:
            w.statement_execution.cancel_execution(stmt.statement_id)
            raise SqlError("Query timed out")
        time.sleep(0.5)
        stmt = w.statement_execution.get_statement(stmt.statement_id)
    if not stmt.status or stmt.status.state != StatementState.SUCCEEDED:
        msg = stmt.status.error.message if stmt.status and stmt.status.error else str(stmt.status)
        raise SqlError(msg)
    cols = [(c.name, c.type_name.value if c.type_name else "STRING") for c in stmt.manifest.schema.columns]
    rows = list(stmt.result.data_array or []) if stmt.result else []
    chunk = stmt.result.next_chunk_index if stmt.result else None
    while chunk:
        part = w.statement_execution.get_statement_result_chunk_n(stmt.statement_id, chunk)
        rows.extend(part.data_array or [])
        chunk = part.next_chunk_index
    return [{n: _convert(v, t) for (n, t), v in zip(cols, r)} for r in rows]


def cached(key: str, ttl: float, fn):
    key = f"{current_persona()}|{key}"
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = fn()
    with _lock:
        _cache[key] = (now, value)
    return value


def clear_cache():
    with _lock:
        _cache.clear()


def parallel(**jobs):
    futures = {k: _pool.submit(contextvars.copy_context().run, fn) for k, fn in jobs.items()}
    return {k: f.result() for k, f in futures.items()}
