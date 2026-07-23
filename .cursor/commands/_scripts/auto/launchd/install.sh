#!/usr/bin/env bash
# Install auto-workflow launchd agents for this repo.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# launchd → auto → _scripts → commands → .cursor → repo
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"

LAUNCH_AGENTS="${HOME}/Library/LaunchAgents"
mkdir -p "$LAUNCH_AGENTS"
mkdir -p "$REPO_ROOT/.cursor/auto-workflow/logs"

MODE="${1:-poller}"  # poller | worker | maintenance | summary | both | all

render() {
  local template="$1"
  local dest="$2"
  sed "s|__REPO_ROOT__|${REPO_ROOT}|g" "$template" > "$dest"
  echo "wrote $dest"
}

load_plist() {
  local label="$1"
  local plist="$2"
  launchctl bootout "gui/$(id -u)/${label}" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$plist"
  echo "loaded $label"
}

install_one() {
  local name="$1"
  local dest="$LAUNCH_AGENTS/com.sample-aws.auto-workflow.${name}.plist"
  render "$SCRIPT_DIR/com.sample-aws.auto-workflow.${name}.plist.template" "$dest"
  load_plist "com.sample-aws.auto-workflow.${name}" "$dest"
}

case "$MODE" in
  poller|worker|maintenance|summary)
    install_one "$MODE"
    ;;
  both)
    install_one poller
    install_one worker
    ;;
  all)
    install_one poller
    install_one worker
    install_one maintenance
    install_one summary
    ;;
  *)
    echo "usage: $0 [poller|worker|maintenance|summary|both|all]" >&2
    exit 2
    ;;
esac
