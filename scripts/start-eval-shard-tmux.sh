#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  RUN_VERSION=... scripts/start-eval-shard-tmux.sh CONFIG SHARD_FILE SHARD_ID [tmux-session]

Starts a detached tmux finalizer for one eval shard. This is eval-only: it runs
run-config.py finalize with explicit --instance args from SHARD_FILE and never
publishes.

Environment:
  RUN_VERSION=VERSION       Required run version to evaluate.
  PROGRAMBENCH_REPO=PATH    ProgramBench checkout (default: $HOME/ProgramBench when present).
  NODE_LABEL=LABEL          Human-readable node label printed into the log.
  NODE_ROLE=ROLE            Optional role label, for example eval-worker or coordinator.
  UV_BIN=PATH               Optional uv binary override.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

uv_bin() {
  if [[ -n "${UV_BIN:-}" ]]; then
    printf '%s\n' "$UV_BIN"
  elif command -v uv >/dev/null; then
    command -v uv
  elif [[ -x /usr/local/bin/uv ]]; then
    printf '%s\n' /usr/local/bin/uv
  elif [[ -x "$HOME/.local/bin/uv" ]]; then
    printf '%s\n' "$HOME/.local/bin/uv"
  else
    echo "uv not found; run scripts/bootstrap-linux-vm.sh or set UV_BIN" >&2
    exit 1
  fi
}

if [[ "${1:-}" == "--run-inside-tmux" ]]; then
  : "${CONFIG:?missing CONFIG}"
  : "${SHARD_FILE:?missing SHARD_FILE}"
  : "${SHARD_ID:?missing SHARD_ID}"
  : "${RUN_VERSION:?missing RUN_VERSION}"
  : "${PROGRAMBENCH_REPO:?missing PROGRAMBENCH_REPO}"
  : "${UV_BIN:?missing UV_BIN}"

  instance_args=()
  instance_count=0
  while IFS= read -r instance || [[ -n "$instance" ]]; do
    instance="${instance%$'\r'}"
    if [[ "$instance" == \#* ]]; then
      continue
    fi
    if [[ -n "$instance" ]]; then
      instance_args+=(--instance "$instance")
      instance_count=$((instance_count + 1))
    fi
  done < "$SHARD_FILE"

  echo "node_label=${NODE_LABEL:-$(hostname)}"
  echo "node_role=${NODE_ROLE:-eval-worker}"
  echo "shard_id=$SHARD_ID"
  echo "run_version=$RUN_VERSION"
  echo "config=$CONFIG"
  echo "shard_file=$SHARD_FILE"
  echo "instances=$instance_count"
  echo "publish=false"
  "$UV_BIN" run python scripts/run-config.py finalize "$CONFIG" \
    --programbench-repo "$PROGRAMBENCH_REPO" \
    --allow-partial \
    "${instance_args[@]}"
  exit 0
fi

CONFIG="${1:-}"
SHARD_FILE="${2:-}"
SHARD_ID="${3:-}"
SESSION="${4:-}"

if [[ -z "$CONFIG" || -z "$SHARD_FILE" || -z "$SHARD_ID" ]]; then
  usage >&2
  exit 2
fi
if [[ ! -f "$CONFIG" ]]; then
  echo "config not found: $CONFIG" >&2
  exit 1
fi
if [[ ! -f "$SHARD_FILE" ]]; then
  echo "shard file not found: $SHARD_FILE" >&2
  exit 1
fi
if [[ -z "${RUN_VERSION:-}" ]]; then
  echo "RUN_VERSION is required" >&2
  exit 1
fi
if [[ -z "${PROGRAMBENCH_REPO:-}" && -d "$HOME/ProgramBench" ]]; then
  PROGRAMBENCH_REPO="$HOME/ProgramBench"
fi
if [[ -z "${PROGRAMBENCH_REPO:-}" ]]; then
  echo "PROGRAMBENCH_REPO is required" >&2
  exit 1
fi

UV_BIN="$(uv_bin)"
export CONFIG SHARD_FILE SHARD_ID RUN_VERSION PROGRAMBENCH_REPO UV_BIN

if [[ -z "$SESSION" ]]; then
  SESSION="goalbench-eval-shard-${SHARD_ID}-${RUN_VERSION}"
fi
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session already exists: $SESSION" >&2
  exit 1
fi

mkdir -p local_state/logs
log="local_state/logs/${SESSION}.log"
cmd=(env)
for key in CONFIG SHARD_FILE SHARD_ID RUN_VERSION PROGRAMBENCH_REPO UV_BIN NODE_LABEL NODE_ROLE; do
  if [[ -n "${!key:-}" ]]; then
    cmd+=("$key=${!key}")
  fi
done
cmd+=(bash scripts/start-eval-shard-tmux.sh --run-inside-tmux)

tmux new-session -d -s "$SESSION" -c "$PWD" "$(printf '%q ' "${cmd[@]}") 2>&1 | tee -a $(printf '%q' "$log")"

echo "started eval shard: $SESSION"
echo "node_label=${NODE_LABEL:-$(hostname)}"
echo "node_role=${NODE_ROLE:-eval-worker}"
echo "shard_id=$SHARD_ID"
echo "publish=false"
echo "log: $log"
