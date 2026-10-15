"""Stream state claim events into the bronze landing table through Zerobus Ingest.

Each state outbox is drained by its own producer thread, the way ten agencies
would push independently. Records go to the Zerobus REST endpoint as JSON
batches authenticated with an OAuth M2M token scoped to the landing table.
"""

import argparse
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from databricks.sdk import WorkspaceClient
from pyspark.dbutils import DBUtils
from pyspark.sql import SparkSession

parser = argparse.ArgumentParser()
parser.add_argument("--catalog", default="lanl")
parser.add_argument("--schema", default="dol_ui")
parser.add_argument("--secret_scope", default="dol_ui")
parser.add_argument("--zerobus_endpoint", default="")
parser.add_argument("--region", default="us-east-1")
parser.add_argument("--batch_size", type=int, default=400)
parser.add_argument("--max_events", type=int, default=0, help="0 drains every pending event")
args, _ = parser.parse_known_args()

spark = SparkSession.builder.getOrCreate()
dbutils = DBUtils(spark)
ns = f"{args.catalog}.{args.schema}"
table = f"{ns}.bronze_claim_events"

w = WorkspaceClient()
workspace_url = w.config.host.rstrip("/")
workspace_id = w.get_workspace_id()
endpoint = (args.zerobus_endpoint or f"https://{workspace_id}.zerobus.{args.region}.cloud.databricks.com").rstrip("/")

client_id = dbutils.secrets.get(args.secret_scope, "zerobus_client_id")
client_secret = dbutils.secrets.get(args.secret_scope, "zerobus_client_secret")

catalog, schema = args.catalog, args.schema
authorization_details = json.dumps([
    {"type": "unity_catalog_privileges", "privileges": ["USE CATALOG"], "object_type": "CATALOG", "object_full_path": catalog},
    {"type": "unity_catalog_privileges", "privileges": ["USE SCHEMA"], "object_type": "SCHEMA", "object_full_path": ns},
    {"type": "unity_catalog_privileges", "privileges": ["SELECT", "MODIFY"], "object_type": "TABLE", "object_full_path": table},
])

_token = {"value": None, "expires": 0.0}
_lock = threading.Lock()


def token():
    with _lock:
        if _token["value"] and time.time() < _token["expires"] - 120:
            return _token["value"]
        r = requests.post(
            f"{workspace_url}/oidc/v1/token",
            auth=(client_id, client_secret),
            data={
                "grant_type": "client_credentials",
                "scope": "all-apis",
                "resource": f"api://databricks/workspaces/{workspace_id}/zerobusDirectWriteApi",
                "authorization_details": authorization_details,
            },
            timeout=30,
        )
        r.raise_for_status()
        body = r.json()
        _token["value"] = body["access_token"]
        _token["expires"] = time.time() + int(body.get("expires_in", 3600))
        return _token["value"]


session = requests.Session()
insert_url = f"{endpoint}/zerobus/v1/tables/{table}/insert"


def send(records):
    for attempt in range(6):
        r = session.post(insert_url, headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"}, data=json.dumps(records), timeout=60)
        if r.status_code == 200:
            return len(records)
        if r.status_code in (401, 403):
            _token["value"] = None
        if r.status_code < 500 and r.status_code not in (401, 403, 429):
            raise RuntimeError(f"Zerobus rejected batch: HTTP {r.status_code} {r.text[:500]}")
        time.sleep(min(30, 2 ** attempt + random.random()))
    raise RuntimeError(f"Zerobus batch failed after retries: HTTP {r.status_code} {r.text[:300]}")


pending = spark.sql(f"""
  SELECT o.event_id, o.state_code, o.agency, o.event_ts_unix_us, o.payload
  FROM {ns}.ref_state_outbox o
  LEFT ANTI JOIN {table} b ON o.event_id = b.event_id
  ORDER BY o.event_ts_unix_us
""")
if args.max_events:
    pending = pending.limit(args.max_events)
rows = [r.asDict() for r in pending.collect()]
print(f"Zerobus endpoint {endpoint}; {len(rows):,} pending events")

by_state = {}
for r in rows:
    by_state.setdefault(r["state_code"], []).append(r)


def drain(state, events):
    sent = 0
    for i in range(0, len(events), args.batch_size):
        now_us = int(time.time() * 1_000_000)
        batch = [{
            "event_id": e["event_id"],
            "state_code": e["state_code"],
            "agency": e["agency"],
            "event_ts": e["event_ts_unix_us"],
            "ingested_at": now_us,
            "payload": e["payload"],
        } for e in events[i:i + args.batch_size]]
        sent += send(batch)
    return state, sent


total = 0
start = time.time()
with ThreadPoolExecutor(max_workers=len(by_state) or 1) as pool:
    for f in as_completed([pool.submit(drain, s, evs) for s, evs in by_state.items()]):
        state, sent = f.result()
        total += sent
        print(f"  {state}: {sent:,} events streamed")
print(f"Streamed {total:,} events through Zerobus in {time.time() - start:.1f}s")
