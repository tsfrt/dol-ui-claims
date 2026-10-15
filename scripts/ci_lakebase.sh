#!/usr/bin/env bash
# Resolve (and optionally create) a Lakebase branch for CI, then export connection settings.
#   scripts/ci_lakebase.sh <branch> [--create]
# Writes ENDPOINT_NAME, PGHOST, and DATABASE_URL to $GITHUB_ENV when running in GitHub Actions.
set -euo pipefail

PROJECT="${LAKEBASE_PROJECT:-dol-ui}"
BRANCH="$1"
BRANCH_PATH="projects/${PROJECT}/branches/${BRANCH}"
ENDPOINT="${BRANCH_PATH}/endpoints/primary"

if [[ "${2:-}" == "--create" ]]; then
  if ! databricks postgres get-branch "${BRANCH_PATH}" >/dev/null 2>&1; then
    databricks postgres create-branch "projects/${PROJECT}" "${BRANCH}" \
      --json "{\"spec\": {\"source_branch\": \"projects/${PROJECT}/branches/production\", \"no_expiry\": true}}"
  fi
  if ! databricks postgres get-endpoint "${ENDPOINT}" >/dev/null 2>&1; then
    databricks postgres create-endpoint "${BRANCH_PATH}" primary \
      --json '{"spec": {"endpoint_type": "ENDPOINT_TYPE_READ_WRITE", "autoscaling_limit_min_cu": 0.5, "autoscaling_limit_max_cu": 1}}'
  fi
fi

HOST=$(databricks postgres get-endpoint "${ENDPOINT}" -o json | jq -r '.status.hosts.host')
TOKEN=$(databricks postgres generate-database-credential "${ENDPOINT}" -o json | jq -r '.token')
USER_NAME="${DATABRICKS_CLIENT_ID:-$(databricks current-user me -o json | jq -r '.userName')}"
ENC_USER=$(jq -rn --arg v "${USER_NAME}" '$v|@uri')
URL="postgresql://${ENC_USER}:${TOKEN}@${HOST}:5432/databricks_postgres?sslmode=require"

if [[ -n "${GITHUB_ENV:-}" ]]; then
  echo "::add-mask::${TOKEN}"
  {
    echo "ENDPOINT_NAME=${ENDPOINT}"
    echo "PGHOST=${HOST}"
    echo "DATABASE_URL=${URL}"
  } >> "${GITHUB_ENV}"
else
  echo "ENDPOINT_NAME=${ENDPOINT}"
  echo "PGHOST=${HOST}"
fi
