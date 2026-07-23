#!/usr/bin/env bash
# Run harness tiers 1..MAX in order (default 4 — task scope; use 6 for
# story/spec scope). Exit 2 from a tier means SKIP (keep going); any other
# non-zero exit stops the run — first failure wins.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
MAX="${1:-4}"

TIERS=(
  test-tier1-lint.sh
  test-tier2-unit.sh
  test-tier3-security.sh
  test-tier4-integration.sh
  test-tier5-multiservice.sh
  test-tier6-product.sh
)

for ((i = 1; i <= MAX && i <= ${#TIERS[@]}; i++)); do
  script="$DIR/${TIERS[i - 1]}"
  if [[ ! -f "$script" ]]; then
    echo "tiers: tier$i missing ($script) — skipped"
    continue
  fi
  bash "$script"
  code=$?
  if [[ "$code" -eq 0 ]]; then
    continue
  fi
  if [[ "$code" -eq 2 ]]; then
    echo "tiers: tier$i skipped"
    continue
  fi
  echo "tiers: tier$i FAILED (exit $code) — stopping" >&2
  exit "$code"
done

echo "tiers: 1-$MAX complete"
