#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f scripts/test-tier1-local.sh ]]; then
  exec bash scripts/test-tier1-local.sh
fi

run() { echo ">> $*"; "$@"; }

ran=0

# Python (Lambda, uv, poetry, etc.)
if [[ -f pyproject.toml ]]; then
  if command -v uv >/dev/null 2>&1 && [[ -f uv.lock ]]; then
    UV_WRAP=(uv run)
  else
    UV_WRAP=()
  fi
  if [[ -f ruff.toml ]] || grep -q '\[tool\.ruff' pyproject.toml 2>/dev/null; then
    if ((${#UV_WRAP[@]})); then
      run "${UV_WRAP[@]}" ruff check .
    elif command -v ruff >/dev/null 2>&1; then
      run ruff check .
    elif command -v python3 >/dev/null 2>&1; then
      run python3 -m ruff check .
    else
      echo "tier1: ruff configured but ruff not on PATH (no-op)" >&2
    fi
    ran=1
  fi
  if grep -q '\[tool\.mypy' pyproject.toml 2>/dev/null; then
    if ((${#UV_WRAP[@]})); then
      run "${UV_WRAP[@]}" mypy .
    else
      run mypy .
    fi
    ran=1
  fi
fi

# TypeScript / CDK / Node
if [[ -f package.json ]]; then
  if command -v jq >/dev/null 2>&1 && jq -e '.scripts.lint' package.json >/dev/null 2>&1; then
    run npm run lint
    ran=1
  elif [[ -f tsconfig.json ]] && command -v npx >/dev/null 2>&1; then
    run npx tsc --noEmit
    ran=1
  fi
fi

# Java Lambda
if [[ -f pom.xml ]]; then
  run mvn -q -DskipTests compile checkstyle:check
  ran=1
elif [[ -f build.gradle ]] || [[ -f build.gradle.kts ]]; then
  if [[ -f gradlew ]]; then
    run ./gradlew check -x test
  else
    run gradle check -x test
  fi
  ran=1
fi

if [[ "$ran" -eq 0 ]]; then
  echo "tier1: no lint runner detected (no-op)"
fi

echo "tier1: pass"
