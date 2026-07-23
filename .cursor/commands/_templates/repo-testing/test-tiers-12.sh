#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
bash "$DIR/test-tier1-lint.sh"
bash "$DIR/test-tier2-unit.sh"
