#!/usr/bin/env bash
# Tier 4 — single-service integration: the service under test runs for real,
# everything external mocked or shimmed. For CDK apps a full synth is the
# integration check; LocalStack or per-branch ephemeral-stack checks belong in
# scripts/test-tier4-local.sh.
# Exit 0 = pass, exit 2 = SKIP (no integration surface detected), other = fail.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f scripts/test-tier4-local.sh ]]; then
  exec bash scripts/test-tier4-local.sh
fi

run() { echo ">> $*"; "$@"; }

ran=0

# CDK app — synth resolves every construct and context value for real
if [[ -f cdk.json ]]; then
  if command -v cdk >/dev/null 2>&1; then
    CDK=(cdk)
  elif command -v npx >/dev/null 2>&1; then
    CDK=(npx cdk)
  else
    CDK=()
  fi
  if ((${#CDK[@]})); then
    run "${CDK[@]}" synth --quiet --output cdk.out.tier4
    ran=1
  else
    echo "tier4: cdk.json present but no cdk/npx on PATH" >&2
  fi
fi

# Docker-compose integration stack (service + mocked externals)
if [[ -f docker-compose.test.yml ]] && command -v docker >/dev/null 2>&1; then
  run docker compose -f docker-compose.test.yml up --abort-on-container-exit
  ran=1
fi

if [[ "$ran" -eq 0 ]]; then
  echo "tier4: SKIP — no integration surface detected (add scripts/test-tier4-local.sh)" >&2
  exit 2
fi

echo "tier4: pass"
