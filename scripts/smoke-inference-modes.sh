#!/usr/bin/env bash
set -euo pipefail

INSTANCE="${INSTANCE:-wfxr__csview.8ac4de0}"
RUN_ROOT="${RUN_ROOT:-/tmp/pb-goal-mode-smoke-$(date -u +%Y%m%dT%H%M%SZ)}"
DOCKER_CPUS="${DOCKER_CPUS:-2}"
DOCKER_MEMORY="${DOCKER_MEMORY:-4g}"
TARGET_ACCESS="${TARGET_ACCESS:-wrapper}"
TARGET_WRAPPER_COMMAND="${TARGET_WRAPPER_COMMAND:-sudo -n /usr/local/bin/pb-target-exec}"
MODEL="${MODEL:-gpt-5.5}"
REASONING_EFFORT="${REASONING_EFFORT:-high}"
KEEP_SMOKE="${KEEP_SMOKE:-0}"

MODES=(
  paper
  no-internet
  no-internet-local-tools
)

run() {
  printf '+ %q' "$1"
  shift
  printf ' %q' "$@"
  printf '\n'
  "$@"
}

first_path_line() {
  awk '/^\// {print; exit}'
}

mode_slug() {
  tr -c '[:alnum:]' '-' <<<"$1" | sed 's/^-//; s/-$//'
}

check_package_helper() {
  local mode="$1"
  local instance_dir="$2"
  local solution_dir="$instance_dir/solution"
  local bin_dir="$instance_dir/guard-bin"

  (
    cd "$solution_dir"
    PATH="$bin_dir:$PATH" command -v package-submission >/dev/null
    printf '#!/usr/bin/env bash\nset -euo pipefail\nprintf smoke > executable\nchmod +x executable\n' > compile.sh
    chmod +x compile.sh
    ./compile.sh
    PATH="$bin_dir:$PATH" package-submission >/dev/null
  )
  test -s "$instance_dir/submission.tar.gz"
}

check_guard_behavior() {
  local mode="$1"
  local instance_dir="$2"
  local solution_dir="$instance_dir/solution"
  local guard_dir="$instance_dir/guard-bin"

  case "$mode" in
    paper | no-internet)
      (
        cd "$solution_dir"
        if PATH="$guard_dir:$PATH" rg --files -uu .. >/tmp/pb-smoke-rg.out 2>/tmp/pb-smoke-rg.err; then
          echo "guard allowed parent traversal in $mode" >&2
          exit 1
        fi
        grep -q "blocked rg" /tmp/pb-smoke-rg.err
        if PATH="$guard_dir:$PATH" curl --version >/tmp/pb-smoke-curl.out 2>/tmp/pb-smoke-curl.err; then
          echo "guard allowed curl in $mode" >&2
          exit 1
        fi
        grep -q "blocked curl" /tmp/pb-smoke-curl.err
      )
      ;;
    no-internet-local-tools)
      (
        cd "$solution_dir"
        if PATH="$guard_dir:$PATH" curl --version >/tmp/pb-smoke-curl.out 2>/tmp/pb-smoke-curl.err; then
          echo "guard allowed curl in $mode" >&2
          exit 1
        fi
        grep -q "blocked curl" /tmp/pb-smoke-curl.err
        PATH="$guard_dir:$PATH" strings --version >/dev/null
      )
      ;;
  esac
}

check_codex_permissions() {
  local instance_dir="$1"
  codex --yolo --version >/dev/null
  grep -q -- "--yolo" "$instance_dir/start-codex-goal.sh"
  grep -q -- "--dangerously-bypass-approvals-and-sandbox" "$instance_dir/start-codex-goal.sh"
  grep -q -- "--enable goals" "$instance_dir/start-codex-goal.sh"
}

cleanup_container() {
  local instance_dir="$1"
  local container
  container="$(jq -r .container_name "$instance_dir/run.json")"
  docker rm -f "$container" >/dev/null 2>&1 || true
}

main() {
  mkdir -p "$RUN_ROOT"
  echo "smoke run root: $RUN_ROOT"
  echo "instance: $INSTANCE"

  for mode in "${MODES[@]}"; do
    echo
    echo "== $mode =="
    run_name="smoke-$(mode_slug "$mode")-$INSTANCE"
    output="$(
      python3 programbench_goal_runner.py prepare "$INSTANCE" \
        --run-root "$RUN_ROOT" \
        --run-name "$run_name" \
        --docker-cpus "$DOCKER_CPUS" \
        --docker-memory "$DOCKER_MEMORY" \
        --inference-mode "$mode" \
        --target-access "$TARGET_ACCESS" \
        --target-wrapper-command "$TARGET_WRAPPER_COMMAND" \
        --model "$MODEL" \
        --reasoning-effort "$REASONING_EFFORT"
    )"
    instance_dir="$(first_path_line <<<"$output")"
    test -n "$instance_dir"
    echo "$instance_dir"

    run start-target "$instance_dir/start-target.sh"
    run check-compliance "$instance_dir/check-compliance.sh"
    check_package_helper "$mode" "$instance_dir"
    check_guard_behavior "$mode" "$instance_dir"
    check_codex_permissions "$instance_dir"
    if [[ "$KEEP_SMOKE" != "1" ]]; then
      cleanup_container "$instance_dir"
    fi
    echo "ok: $mode"
  done
}

main "$@"
