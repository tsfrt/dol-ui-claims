"""Turn the staged Delta Sharing states into real Databricks-to-Databricks shares.

Ohio, Colorado and North Carolina keep their UI claim status logs on Databricks.
Each state publishes a targeted share to US DOL ETA: one table, with history so
DOL can stream its change feed, granted to the DOL recipient only.

Provider side (run against the state's workspace, on a different metastore; needs
CREATE SHARE and CREATE RECIPIENT there, and the state tables must exist in it):
  python scripts/setup_state_shares.py provider --profile <state-profile> --warehouse <id> \
      --recipient-id aws:us-east-1:c0da88f1-c020-4992-b8c9-c828e556889d [--apply]

Recipient side (run against this workspace; needs CREATE CATALOG and USE PROVIDER):
  python scripts/setup_state_shares.py recipient --profile fevm-serverless-stable-blj52t --warehouse 688f49c732cf9083 \
      --provider <provider name> [--apply]

Then point the pipeline at the mounted catalogs and full-refresh:
  databricks bundle deploy --var share_catalog_oh=oh_share --var share_catalog_co=co_share --var share_catalog_nc=nc_share

Without --apply the script prints the SQL it would run.
"""

import argparse
import os
import sys
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "pipelines"))
from state_specs import SHARE_STATES, STATE_SPECS, share_staged_table  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument("side", choices=["provider", "recipient"])
p.add_argument("--profile", required=True)
p.add_argument("--warehouse", required=True)
p.add_argument("--catalog", default="lanl", help="Catalog that holds the state tables on the provider side")
p.add_argument("--recipient", default="usdol_eta")
p.add_argument("--recipient-id", default="", help="Sharing identifier of the DOL metastore (provider side)")
p.add_argument("--provider", default="", help="Provider name as it appears in the DOL metastore (recipient side)")
p.add_argument("--apply", action="store_true")
args = p.parse_args()


def statements():
    if args.side == "provider":
        if not args.recipient_id:
            sys.exit("--recipient-id is required on the provider side")
        yield f"CREATE RECIPIENT IF NOT EXISTS {args.recipient} USING ID '{args.recipient_id}' COMMENT 'US DOL Employment and Training Administration'"
        for state in SHARE_STATES:
            s = STATE_SPECS[state]["share"]
            yield f"CREATE SHARE IF NOT EXISTS {s['name']} COMMENT '{STATE_SPECS[state]['agency']} UI claim status log for US DOL ETA'"
            yield f"ALTER SHARE {s['name']} ADD TABLE {share_staged_table(args.catalog, state)} AS uia.{s['table']} WITH HISTORY"
            yield f"GRANT SELECT ON SHARE {s['name']} TO RECIPIENT {args.recipient}"
    else:
        if not args.provider:
            sys.exit("--provider is required on the recipient side")
        for state in SHARE_STATES:
            s = STATE_SPECS[state]["share"]
            yield f"CREATE CATALOG IF NOT EXISTS {state.lower()}_share USING SHARE `{args.provider}`.{s['name']} COMMENT 'Delta Share from {STATE_SPECS[state]['agency']}'"


w = WorkspaceClient(profile=args.profile) if args.apply else None
for sql in statements():
    print(sql + ";")
    if not w:
        continue
    r = w.statement_execution.execute_statement(statement=sql, warehouse_id=args.warehouse, wait_timeout="50s")
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        sys.exit(f"  failed: {r.status.error.message if r.status.error else r.status.state}")
