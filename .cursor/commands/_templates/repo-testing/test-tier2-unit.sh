#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f scripts/test-tier2-local.sh ]]; then
  exec bash scripts/test-tier2-local.sh
fi

run() { echo ">> $*"; "$@"; }

has_pytest_tests() {
  find . \( -path ./.venv -o -path ./.git -o -path ./node_modules \) -prune -o \
    \( -name 'test_*.py' -o -name '*_test.py' \) -print -quit | grep -q .
}

# Python
if [[ -f pyproject.toml ]]; then
  if command -v uv >/dev/null 2>&1 && [[ -f uv.lock ]]; then
    UV_WRAP=(uv run)
  else
    UV_WRAP=()
  fi
  if ! has_pytest_tests; then
    echo "tier2: SKIP — no unit tests found" >&2
    exit 2
  fi
  if ((${#UV_WRAP[@]})); then
    run "${UV_WRAP[@]}" pytest -q
  else
    run pytest -q
  fi
  echo "tier2: pass"
  exit 0
fi

# TypeScript / Node
if [[ -f package.json ]] && command -v jq >/dev/null 2>&1 && jq -e '.scripts.test' package.json >/dev/null 2>&1; then
  run npm test
  echo "tier2: pass"
  exit 0
fi

# Java
if [[ -f pom.xml ]]; then
  run mvn -q test
  echo "tier2: pass"
  exit 0
elif [[ -f build.gradle ]] || [[ -f build.gradle.kts ]]; then
  if [[ -f gradlew ]]; then
    run ./gradlew test
  else
    run gradle test
  fi
  echo "tier2: pass"
  exit 0
fi

echo "tier2: SKIP — no test runner detected" >&2
exit 2
