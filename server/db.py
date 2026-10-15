import os

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from server.config import get_workspace_client

ENDPOINT_NAME = os.environ.get("ENDPOINT_NAME", "projects/dol-ui/branches/production/endpoints/primary")
HAS_LAKEBASE = bool(os.environ.get("PGHOST"))

_w = None


class OAuthConnection(psycopg.Connection):
    @classmethod
    def connect(cls, conninfo="", **kwargs):
        global _w
        if _w is None:
            _w = get_workspace_client()
        kwargs["password"] = _w.postgres.generate_database_credential(endpoint=ENDPOINT_NAME).token
        return super().connect(conninfo, **kwargs)


def _build_pool() -> ConnectionPool | None:
    if not HAS_LAKEBASE:
        return None
    conninfo = (
        f"dbname={os.environ.get('PGDATABASE', 'databricks_postgres')} user={os.environ['PGUSER']} "
        f"host={os.environ['PGHOST']} port={os.environ.get('PGPORT', '5432')} sslmode={os.environ.get('PGSSLMODE', 'require')}"
    )
    return ConnectionPool(conninfo=conninfo, connection_class=OAuthConnection, min_size=1, max_size=8, max_lifetime=2700, open=False, kwargs={"row_factory": dict_row})


pool = _build_pool()


def query(sql: str, params: tuple | dict | None = None) -> list[dict]:
    if pool is None:
        return []
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        return list(cur.fetchall()) if cur.description else []


def execute(sql: str, params: tuple | dict | None = None) -> list[dict]:
    if pool is None:
        return []
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            rows = list(cur.fetchall()) if cur.description else []
        conn.commit()
        return rows


def safe_query(sql: str, params=None) -> list[dict]:
    try:
        return query(sql, params)
    except Exception as e:  # noqa: BLE001
        print(f"Lakebase query failed: {e}")
        return []
