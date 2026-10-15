#!/usr/bin/env bash
# Require an approved pull request (and a green preview deploy) for every change to main.
#   scripts/protect_main.sh <owner/repo>
set -euo pipefail
REPO="$1"
gh api -X PUT "repos/${REPO}/branches/main/protection" --input - <<'EOF'
{
  "required_status_checks": { "strict": true, "contexts": ["preview"] },
  "enforce_admins": true,
  "required_pull_request_reviews": { "required_approving_review_count": 1, "dismiss_stale_reviews": true },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
echo "main is protected: approved PR + passing preview check required"
