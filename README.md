# DOL UI Claims Integrity Command Center

Synthetic U.S. Department of Labor demo on Databricks:

- **Ingest:** ten state workforce agencies push inconsistent unemployment insurance (UI) claim status events through **Zerobus Ingest**; Michigan drops weekly MiWAM CSV extracts into a Unity Catalog volume that **Auto Loader** pulls into the same bronze stream; Ohio, Colorado and North Carolina already run on Databricks and give DOL a targeted **Delta Share** of their claim status log, which the pipeline reads as a change feed.
- **Pipeline:** **Lakeflow Spark Declarative Pipelines** normalize the events and cross-match federal intel.
- **Detection:** three independent techniques flag fraud and ineligibility: Python rules, a behavioral ML model, and **Genie Agents in Agent mode**.
- **App:** a Databricks App serves the analyst command center, and **Lakebase** stores configuration and analyst decisions.

Workspace: [fevm-serverless-stable-blj52t](https://fevm-serverless-stable-blj52t.cloud.databricks.com/?o=7474656503943141) · Catalog/schema `lanl.dol_ui`

All person data is fake. Intel tables are modeled on SSA DMF, BOP SENTRY, HHS NDNH, SSA identity verification, Treasury Do Not Pay, and BLS LAUS. None of them are connected to those systems.

## Architecture

| Layer | What runs | Where |
| --- | --- | --- |
| State systems | Each state sends its own JSON contract: field names, status codes, SSN, date and week formats, and amounts in cents, dollars, or `"$1,234.00"` | `src/pipelines/state_specs.py` |
| Ingest (push) | One producer thread per state drains its outbox to the Zerobus REST API, using OAuth M2M scoped to the landing table | `src/jobs/push_claims.py` → `bronze_claim_events` |
| Ingest (pull) | Michigan publishes one fixed-layout CSV per batch week into the `state_drops` volume; an Auto Loader append flow lands it in the same bronze streaming table, tagged `ingest_channel = 'file_drop'` | `src/jobs/deliver_state_files.py`, `src/pipelines/bronze.py` |
| Ingest (share) | Ohio, Colorado and North Carolina append status changes to typed Delta tables with change data feed. Each table is one targeted share (with history) to the DOL recipient, and an append flow per state streams the change feed into bronze, tagged `ingest_channel = 'delta_share'`. **Staged:** until the shares can be created, the tables live in per-state schemas (`lanl.state_oh_odjfs`, `lanl.state_co_cdle`, `lanl.state_nc_des`), and the app labels the channel "staged". | `src/jobs/deliver_state_shares.py`, `src/pipelines/bronze.py`, `scripts/setup_state_shares.py` |
| Normalize | Spec-driven parser with expectations, SCD2 claim history, claims, weeks, a cross-state profile, identity links, interstate pairs, and state summaries | `src/pipelines/*.py` |
| Rules | 10 Python rules: 6 fraud (DMF, BOP, NDNH, ICON, SSA identity, Do Not Pay) and 4 eligibility (monetary, separation, work search, entitlement) | `src/pipelines/rules.py` → `gold_check_findings` |
| ML | Gradient boosting on behavioral features only (shared bank, device, subnet; employer concentration; wage-history shape). Logs evaluation to MLflow and UC tables, registers the model in UC. | `src/jobs/train_eval.py` |
| Agent | The Genie agent investigates priority cases in Agent mode and writes verdict, report, and SQL trace | `src/jobs/genie_review.py`, `src/genie/agent.py` |
| Analyst rules | Rule studio: Foundation Model API turns plain English into SQL grounded in UC metadata, backtests it against adjudicated outcomes, and gates promotion (precision ≥ 60%, hit rate ≤ 15%). Definitions live in Lakebase `custom_rules`; the jobs re-apply active rules after every refresh. | `server/rule_studio.py`, `src/jobs/apply_custom_rules.py` → `gold_custom_rule_findings` |
| Governance | Governed tags on PII and state columns; five ABAC policies on the schema (three column masks, two row filters) driven by the `ref_data_entitlements` registry. The pipeline owner is in each policy's `EXCEPT` clause, so materialized views are built unfiltered. | `src/jobs/governance.py` |
| App | FastAPI plus React (Vite) with a d3 US map, Applicant 360, model evaluation, Rule studio, Access & governance (View-as personas backed by real service principals) and a live Architecture page. Lakebase holds config, rule toggles, notes, dispositions, agent runs and analyst rules. | `app.py`, `server/`, `frontend/` |

Jobs:

- `dol_ui_orchestrate` rebuilds everything: seed, stream, full-refresh SDP, train, then agent review.
- `dol_ui_stream_and_score` streams any remaining outbox events, delivers held-back Michigan files, and rescores incrementally. The rebuild holds back the newest Michigan file (`hold_back_files=1`), so "Run a micro-batch now" on the Architecture page shows a file arriving live. For a bigger moment, also run `dol_ui_orchestrate` with `max_events=30000`.

Delta Sharing switch-over: a provider workspace on another metastore runs `scripts/setup_state_shares.py provider ... --apply`, which creates the `usdol_eta` recipient and one share per state. In this workspace, `scripts/setup_state_shares.py recipient ... --apply` mounts `oh_share`, `co_share` and `nc_share`; that needs `CREATE CATALOG` and `USE PROVIDER`. Then deploy with `--var share_catalog_oh=oh_share` (and the CO and NC equivalents) and run a full refresh. The pipeline reads the mounted shares, and the app drops the "staged" label.

Lakehouse Federation: `scripts/setup_federation.py` creates Michigan's "UI tax wage records" Postgres database on the Lakebase project (with a read-only password role) and registers it as the foreign catalog `mi_uia_tax`. Registering it needs `CREATE CONNECTION` and `CREATE CATALOG` on the metastore, plus `enable_pg_native_login` on the Lakebase project. The Architecture page shows the federated source once the catalog is readable.

## Demo walkthrough

1. **Command center:** KPIs, then the state map. Fill shows the flagged share, and arcs show claimants paid by two states for the same weeks. Click a state to see its raw payload, its status vocabulary mapped to canonical, and its field mapping.
2. **Detection coverage:** rules and ML overlap. The "ML only" callout counts fraud-ring members that pass every rule.
3. **Case queue:** filter to **ML only**. Open a ring member: Rules says *Eligible* and ML says *Fraud*. The linked-identities graph shows the shared device or bank account.
4. **Run Agent mode investigation:** the agent plans, runs SQL across claims, intel, and links, and returns a verdict while its trace streams in.
5. Open a deceased or interstate claimant. The claim swimlane shows paid weeks after the date of death, or overlapping state lanes.
6. Record a determination. It's written to Lakebase.
7. **Detection models:** ROC, confusion matrix, permutation importance, and lift over rules. Toggle a rule to show that rules are configurable.
8. **Rule studio:** type a multi-state rule in plain English (for example "Flag claimants paid by three or more states for overlapping weeks"). Review the SQL, the backtest against adjudicated outcomes, and the validation gates. Save it, then promote it; its findings join the case queue. You can deep-link with `#/rules?prompt=...`.
9. **Access & governance:** switch **Viewing as** to *CA EDD state analyst*. The same queries now return California rows only, with names, DOB and SSN masked by Unity Catalog. Edit the entitlement to add a state and watch the next query change.
10. **Architecture:** the live platform diagram (push and pull ingest, SDP, the three techniques plus analyst rules, App, Lakebase and UC), CI/CD, and the APIs behind each step. "Run a micro-batch now" delivers the held-back Michigan file.

Personas: the service principals `dol-ui-persona-federal-analyst` and `dol-ui-persona-ca-state-analyst` hold OAuth secrets in `dol_ui/persona_*`. The app reads them as secret resources and runs SQL as the selected persona.

## Setup notes

- Zerobus producer service principal `dol-ui-zerobus-producer`. Its OAuth secret is in secret scope `dol_ui` (`zerobus_client_id`, `zerobus_client_secret`). The seed task re-grants `MODIFY`/`SELECT` on the landing table.
- Create or update the Genie agent with `python scripts/setup_genie.py [--space-id ID]`. Its ID is stored in bundle var `genie_space_id` and in Lakebase `app_config.genie_agent_id`.
- The app service principal needs `USE CATALOG lanl`, `USE SCHEMA` and `SELECT` on `lanl.dol_ui`, plus DML on the Lakebase `public` tables.

## Local app

```bash
cd frontend && npm install && npm run build && cd ..
DATABRICKS_PROFILE=<profile> DATABRICKS_WAREHOUSE_ID=688f49c732cf9083 \
PGHOST=<lakebase host> PGUSER=<you> PGDATABASE=databricks_postgres \
uvicorn app:app --port 8000
```

## CI/CD

- **PR to `main`:** builds the frontend, creates Lakebase branch `pr-<n>` from `production` with its own endpoint, runs Prisma migrations on that branch, then deploys preview app `dol-ui-claims-pr-<n>` bound to the branch.
- **PR closed:** destroys the preview app and deletes the Lakebase branch.
- **Tag `v*` on `main`:** runs Prisma migrations on the `production` branch, then deploys the prod target.
- **Protecting `main`:** run `scripts/protect_main.sh <owner/repo>` so only approved PRs with a passing preview check can merge.
