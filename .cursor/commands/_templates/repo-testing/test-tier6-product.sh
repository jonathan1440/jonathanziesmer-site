#!/usr/bin/env bash
# Tier 6 — product surface: drive the actual UI/endpoints against a deployed
# preview. The agent owns the test plan and may write or revise
# scripts/test-tier6-local.sh during the review loop. Pure-infra stacks with no
# product surface stay skipped.
# Exit 0 = pass, exit 2 = SKIP (no product surface / no plan yet), other = fail.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f scripts/test-tier6-local.sh ]]; then
  exec bash scripts/test-tier6-local.sh
fi

run() { echo ">> $*"; "$@"; }

if compgen -G "playwright.config.*" >/dev/null && command -v npx >/dev/null 2>&1; then
  run npx playwright test
  echo "tier6: pass"
  exit 0
fi

echo "tier6: SKIP — no product surface detected; agent may add scripts/test-tier6-local.sh with the tier-6 test plan" >&2
exit 2
