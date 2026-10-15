"""Stand up the Lakehouse Federation example: Michigan's UI tax wage records.

Michigan's employer quarterly wage detail lives in the state's own Postgres
system and is queried in place through a Unity Catalog foreign catalog rather
than copied. For the demo that system is a separate database on the Lakebase
project with a read-only password role, registered as a POSTGRESQL connection.

Idempotent; re-run after the orchestration job regenerates the population.

  python scripts/setup_federation.py --profile fevm-serverless-stable-blj52t --warehouse 688f49c732cf9083
"""

import argparse
import base64
import secrets as pysecrets
import time

import psycopg
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from databricks.sdk.service.sql import StatementState

p = argparse.ArgumentParser()
p.add_argument("--profile", default=None)
p.add_argument("--warehouse", required=True)
p.add_argument("--catalog", default="lanl")
p.add_argument("--schema", default="dol_ui")
p.add_argument("--project", default="dol-ui")
p.add_argument("--branch", default="production")
p.add_argument("--secret_scope", default="dol_ui")
p.add_argument("--database", default="mi_uia_wages")
p.add_argument("--role", default="mi_federation_reader")
p.add_argument("--connection", default="mi_uia_tax_pg")
p.add_argument("--foreign_catalog", default="mi_uia_tax")
p.add_argument("--grantees", default="472dc3a6-18d1-4b80-88cf-57d27f66b3d1,743cd53d-60cd-42cf-8ab8-6d32d72ea1f3,bc533198-576c-4635-ad84-b79a409e96c8")
args = p.parse_args()

w = WorkspaceClient(profile=args.profile)
me = w.current_user.me().user_name
endpoint = f"projects/{args.project}/branches/{args.branch}/endpoints/primary"
host = w.postgres.get_endpoint(name=endpoint).status.hosts.host
SECRET_KEY = "mi_federation_password"


def sql(statement):
    r = w.statement_execution.execute_statement(statement=statement, warehouse_id=args.warehouse, wait_timeout="50s")
    while r.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        r = w.statement_execution.get_statement(r.statement_id)
    if r.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{statement[:80]}...: {r.status.error.message if r.status.error else r.status.state}")
    return r.result.data_array or [] if r.result else []


def pg(dbname):
    token = w.postgres.generate_database_credential(endpoint=endpoint).token
    return psycopg.connect(host=host, dbname=dbname, user=me, password=token, sslmode="require", autocommit=True)


try:
    password = base64.b64decode(w.secrets.get_secret(args.secret_scope, SECRET_KEY).value).decode()
except NotFound:
    password = pysecrets.token_urlsafe(32)
    w.secrets.put_secret(args.secret_scope, SECRET_KEY, string_value=password)
    print(f"Stored a new federation password in secret {args.secret_scope}/{SECRET_KEY}")

with pg("databricks_postgres") as c:
    if not c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (args.database,)).fetchone():
        c.execute(f'CREATE DATABASE "{args.database}"')
    if c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (args.role,)).fetchone():
        c.execute(psycopg.sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(psycopg.sql.Identifier(args.role), psycopg.sql.Literal(password)))
    else:
        c.execute(psycopg.sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD {}").format(psycopg.sql.Identifier(args.role), psycopg.sql.Literal(password)))

rows = sql(f"""
  SELECT ssn_hash, employer_fein, employer_name, quarter, CAST(quarter_start AS STRING), CAST(wages AS STRING)
  FROM {args.catalog}.{args.schema}.intel_ndnh_quarterly_wages WHERE reporting_state = 'MI'
""")

with pg(args.database) as c:
    c.execute("CREATE SCHEMA IF NOT EXISTS uia_tax")
    c.execute("""
      CREATE TABLE IF NOT EXISTS uia_tax.employer_wage_detail (
        ssn_hash TEXT NOT NULL,
        employer_fein TEXT NOT NULL,
        employer_name TEXT,
        quarter TEXT NOT NULL,
        quarter_start DATE NOT NULL,
        wages NUMERIC(12, 2) NOT NULL,
        reported_at TIMESTAMPTZ NOT NULL DEFAULT now()
      )""")
    c.execute("COMMENT ON TABLE uia_tax.employer_wage_detail IS 'Michigan UIA employer quarterly wage detail from the state UI tax system'")
    c.execute("TRUNCATE uia_tax.employer_wage_detail")
    with c.cursor() as cur:
        with cur.copy("COPY uia_tax.employer_wage_detail (ssn_hash, employer_fein, employer_name, quarter, quarter_start, wages) FROM STDIN") as cp:
            for r in rows:
                cp.write_row(r)
    ident = psycopg.sql.Identifier(args.role)
    c.execute(psycopg.sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(psycopg.sql.Identifier(args.database), ident))
    c.execute(psycopg.sql.SQL("GRANT USAGE ON SCHEMA uia_tax TO {}").format(ident))
    c.execute(psycopg.sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA uia_tax TO {}").format(ident))
print(f"Loaded {len(rows):,} Michigan wage detail rows into {args.database}.uia_tax.employer_wage_detail")

sql(f"""
  CREATE CONNECTION IF NOT EXISTS {args.connection} TYPE postgresql
  OPTIONS (host '{host}', port '5432', user '{args.role}', password secret('{args.secret_scope}', '{SECRET_KEY}'))
  COMMENT 'Michigan UIA UI tax system (Postgres), federated in place'
""")
sql(f"""
  CREATE FOREIGN CATALOG IF NOT EXISTS {args.foreign_catalog} USING CONNECTION {args.connection}
  OPTIONS (database '{args.database}')
  COMMENT 'Michigan UIA wage records queried in place through Lakehouse Federation'
""")
for g in filter(None, args.grantees.split(",")):
    sql(f"GRANT USE CATALOG, USE SCHEMA, SELECT ON CATALOG {args.foreign_catalog} TO `{g}`")
n = sql(f"SELECT count(*) FROM {args.foreign_catalog}.uia_tax.employer_wage_detail")[0][0]
print(f"Foreign catalog {args.foreign_catalog} live: {n} rows readable through Unity Catalog")
