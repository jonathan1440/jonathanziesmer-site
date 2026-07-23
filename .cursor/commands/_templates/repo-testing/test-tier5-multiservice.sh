#!/usr/bin/env bash
# Tier 5 — multi-service integration: real services talking to real services on
# shared staging. Deployment-specific by nature — define the checks in
# scripts/test-tier5-local.sh. Runs at story/spec review, not per task.
# Exit 0 = pass, exit 2 = SKIP (no checks defined), other = fail.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f scripts/test-tier5-local.sh ]]; then
  exec bash scripts/test-tier5-local.sh
fi

echo "tier5: SKIP — no scripts/test-tier5-local.sh; define staging multi-service checks there" >&2
exit 2
