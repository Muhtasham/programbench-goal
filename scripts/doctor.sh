#!/usr/bin/env bash
set -euo pipefail

CONFIG="${1:-configs/linux-smoke-nointernet-xhigh.json}"
PROGRAMBENCH_REPO="${PROGRAMBENCH_REPO:-}"

usage() {
  cat <<'EOF'
Usage:
  scripts/doctor.sh [config]

Checks the local host and selected sweep config before launching an expensive
ProgramBench /goal run. It does not start Codex sessions.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

failures=0

ok() {
  printf 'OK   %s\n' "$1"
}

fail() {
  printf 'FAIL %s\n' "$1" >&2
  failures=$((failures + 1))
}

warn() {
  printf 'WARN %s\n' "$1" >&2
}

need_cmd() {
  command -v "$1" >/dev/null && ok "$1 found: $(command -v "$1")" || fail "$1 not found"
}

config_value() {
  uv run python - "$CONFIG" "$1" <<'PY'
import json
import sys

print(json.loads(open(sys.argv[1]).read())[sys.argv[2]])
PY
}

memory_gib() {
  uv run python - "$1" <<'PY'
import re
import sys

match = re.fullmatch(r"\s*([0-9.]+)\s*([kmgt]?)(i?b)?\s*", sys.argv[1].lower())
if not match:
    raise SystemExit(f"cannot parse memory value: {sys.argv[1]}")
value = float(match[1])
unit = match[2] or "b"
scale = {"b": 1 / 1024**3, "k": 1 / 1024**2, "m": 1 / 1024, "g": 1, "t": 1024}[unit]
print(f"{value * scale:.1f}")
PY
}

if [[ ! -f "$CONFIG" ]]; then
  fail "config not found: $CONFIG"
else
  ok "config found: $CONFIG"
fi

need_cmd git
need_cmd uv
need_cmd docker
need_cmd tmux
need_cmd codex

if [[ "$(uname -s)" == "Linux" ]]; then
  ok "host system Linux"
else
  warn "host system is $(uname -s); use Linux amd64 for reportable runs"
fi

case "$(uname -m)" in
  x86_64 | amd64)
    ok "host machine $(uname -m)"
    ;;
  *)
    warn "host machine is $(uname -m); ProgramBench images are linux/amd64"
    ;;
esac

if command -v docker >/dev/null && docker info >/tmp/pb-doctor-docker-info.txt 2>&1; then
  ok "docker daemon reachable"
  docker_cpus="$(docker info --format '{{.NCPU}}' 2>/dev/null || echo 0)"
  docker_mem_gib="$(docker info --format '{{.MemTotal}}' 2>/dev/null | uv run python -c 'import sys; print(f"{int(sys.stdin.read() or 0) / (1024**3):.1f}")')"
  ok "docker resources: ${docker_cpus} CPUs, ${docker_mem_gib} GiB"
  if [[ -f "$CONFIG" ]]; then
    required_cpus="$(config_value docker_cpus)"
    required_mem_gib="$(memory_gib "$(config_value docker_memory)")"
    if (( docker_cpus < required_cpus )); then
      fail "docker CPUs below config: have ${docker_cpus}, need ${required_cpus}"
    else
      ok "docker CPUs satisfy config: ${required_cpus}"
    fi
    if uv run python - "$docker_mem_gib" "$required_mem_gib" <<'PY'
import sys

raise SystemExit(0 if float(sys.argv[1]) >= float(sys.argv[2]) else 1)
PY
    then
      ok "docker memory satisfies config: ${required_mem_gib} GiB"
    else
      fail "docker memory below config: have ${docker_mem_gib} GiB, need ${required_mem_gib} GiB"
    fi
  fi
else
  fail "docker daemon not reachable"
fi

if [[ -z "$PROGRAMBENCH_REPO" ]]; then
  candidate="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/../ProgramBench"
  if [[ -d "$candidate/src/programbench" ]]; then
    PROGRAMBENCH_REPO="$candidate"
  fi
fi

if [[ -n "$PROGRAMBENCH_REPO" && -d "$PROGRAMBENCH_REPO/src/programbench" ]]; then
  ok "ProgramBench checkout: $(cd "$PROGRAMBENCH_REPO" && pwd)"
  env -u VIRTUAL_ENV uv run --project "$PROGRAMBENCH_REPO" programbench --help >/tmp/pb-doctor-programbench.txt 2>&1 \
    && ok "ProgramBench CLI works" \
    || fail "ProgramBench CLI failed; run scripts/bootstrap-programbench.sh"
else
  fail "ProgramBench checkout not found; run scripts/bootstrap-programbench.sh or set PROGRAMBENCH_REPO"
fi

if [[ -f "$CONFIG" ]]; then
  target_file="$(config_value target_file)"
  target_access="$(config_value target_access)"
  target_wrapper_command="$(config_value target_wrapper_command)"
  if [[ -f "$target_file" ]]; then
    count="$(grep -Ev '^\s*(#|$)' "$target_file" | wc -l | tr -d ' ')"
    ok "target file: $target_file ($count tasks)"
  else
    fail "target file missing: $target_file"
  fi
  if [[ "$target_access" == "wrapper" ]]; then
    set +e
    bash -lc "$target_wrapper_command __pb-wrapper-check true" >/tmp/pb-doctor-wrapper.out 2>/tmp/pb-doctor-wrapper.err
    wrapper_status=$?
    set -e
    if [[ "$wrapper_status" -eq 126 ]]; then
      ok "target wrapper available: $target_wrapper_command"
    else
      fail "target wrapper unavailable; run scripts/install-target-wrapper.sh"
      cat /tmp/pb-doctor-wrapper.err >&2
    fi
  else
    warn "target_access=$target_access; wrapper is preferred for reportable cleanroom runs"
  fi
fi

if command -v codex >/dev/null; then
  ok "codex version: $(codex --version 2>/dev/null || true)"
fi

if [[ "$failures" -ne 0 ]]; then
  printf '\n%s failure(s). Fix these before launching the sweep.\n' "$failures" >&2
  exit 1
fi

printf '\nReady to launch:\n'
printf '  scripts/start-sweep-tmux.sh %s\n' "$CONFIG"
