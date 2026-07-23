#!/usr/bin/env bash
# Tier 7 — rollout monitoring (post-merge, post-deploy): verify staging/production
# logs and metrics against an expected set. The only tier that runs after the
# human review gate. Define the checks in scripts/test-tier7-local.sh (e.g.
# CloudWatch alarm state, error-rate queries per environment).
# On failure: roll back rather than fix-forward, and file the regression as a
# bug sub-issue on the spec.
# Exit 0 = pass, exit 2 = SKIP (no checks defined), other = fail.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f scripts/test-tier7-local.sh ]]; then
  exec bash scripts/test-tier7-local.sh
fi

echo "tier7: SKIP — no scripts/test-tier7-local.sh; define post-deploy log/metric checks there" >&2
exit 2
