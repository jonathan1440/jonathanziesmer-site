#!/usr/bin/env bash
# Tier 3 — security and compliance: secret scan, dependency CVEs, IAM/policy checks.
# Exit 0 = pass, exit 2 = SKIP (no security tooling available), other = fail.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f scripts/test-tier3-local.sh ]]; then
  exec bash scripts/test-tier3-local.sh
fi

run() { echo ">> $*"; "$@"; }

ran=0

# Secret scanning
if command -v gitleaks >/dev/null 2>&1; then
  run gitleaks detect --source . --no-banner --redact
  ran=1
elif command -v trufflehog >/dev/null 2>&1; then
  run trufflehog filesystem --fail .
  ran=1
else
  echo "tier3: no secret scanner on PATH (gitleaks/trufflehog) — secret scan skipped" >&2
fi

# Dependency audit — Python
if compgen -G "requirements*.txt" >/dev/null; then
  if command -v pip-audit >/dev/null 2>&1; then
    for req in requirements*.txt; do
      run pip-audit -r "$req"
    done
    ran=1
  else
    echo "tier3: pip-audit not on PATH — Python dependency audit skipped" >&2
  fi
fi

# Dependency audit — Node
if [[ -f package-lock.json ]]; then
  run npm audit --audit-level=high
  ran=1
fi

# IAM / policy checks — CDK synth output (cdk-nag, when wired into the app, runs
# during synth in tier 4; this scans the synthesized templates directly)
if [[ -f cdk.json ]] && command -v checkov >/dev/null 2>&1; then
  synth_dir=""
  [[ -d cdk.out.tier4 ]] && synth_dir=cdk.out.tier4
  [[ -z "$synth_dir" && -d cdk.out ]] && synth_dir=cdk.out
  if [[ -n "$synth_dir" ]]; then
    run checkov --quiet --framework cloudformation -d "$synth_dir"
    ran=1
  else
    echo "tier3: no synth output yet — run tier 4 first for the checkov policy scan" >&2
  fi
fi

if [[ "$ran" -eq 0 ]]; then
  echo "tier3: SKIP — no security tooling ran (install gitleaks/pip-audit/checkov, or add scripts/test-tier3-local.sh)" >&2
  exit 2
fi

echo "tier3: pass"
