#!/usr/bin/env bash
set -euo pipefail

CONFIG="${1:-configs/linux-smoke-nointernet-xhigh.json}"
SESSION="${2:-}"
PROGRAMBENCH_REPO="${PROGRAMBENCH_REPO:-}"

usage() {
  cat <<'EOF'
Usage:
  scripts/start-sweep-tmux.sh [config] [tmux-session]

Starts scripts/run-sweep.sh in a detached tmux session and logs output under
local_state/logs/. PROGRAMBENCH_REPO is passed through when set; otherwise
run-sweep.sh auto-detects a sibling ../ProgramBench checkout.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ ! -f "$CONFIG" ]]; then
  echo "config not found: $CONFIG" >&2
  exit 1
fi

if [[ -z "$SESSION" ]]; then
  batch_name="$(uv run python - "$CONFIG" <<'PY'
import json
import sys

print(json.loads(open(sys.argv[1]).read())["batch_name"])
PY
)"
  SESSION="pb-goal-${batch_name}"
fi

mkdir -p local_state/logs
log="local_state/logs/${SESSION}.log"

if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session already exists: $SESSION" >&2
  echo "attach with: tmux attach -t $SESSION" >&2
  exit 1
fi

cmd=(scripts/run-sweep.sh --config "$CONFIG" --allow-partial)
if [[ -n "$PROGRAMBENCH_REPO" ]]; then
  cmd+=(--programbench-repo "$PROGRAMBENCH_REPO")
fi

tmux new-session -d -s "$SESSION" -c "$PWD" "$(printf '%q ' "${cmd[@]}") 2>&1 | tee -a $(printf '%q' "$log")"

echo "started tmux session: $SESSION"
echo "log: $log"
echo "attach: tmux attach -t $SESSION"
echo "status: uv run python scripts/run-config.py status $CONFIG"
