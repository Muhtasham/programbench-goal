#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shlex
import shutil
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ROOT = Path.home() / "pb-goal-runs"
PROMPT_TEMPLATE = Path(__file__).parent / "prompts" / "programbench_goal.md"
NO_INTERNET_PROMPT_TEMPLATE = Path(__file__).parent / "prompts" / "programbench_goal_no_internet.md"
LOCAL_TOOLS_PROMPT_TEMPLATE = Path(__file__).parent / "prompts" / "programbench_goal_local_tools.md"
OPEN_PROMPT_TEMPLATE = Path(__file__).parent / "prompts" / "programbench_goal_open.md"
DEFAULT_MODEL = "gpt-5.5"
DEFAULT_REASONING_EFFORT = "xhigh"
DEFAULT_INFERENCE_MODE = "no-internet"
MODE_RUN_SEGMENTS = {
    "paper": "paper",
    "no-internet": "nointernet",
    "no-internet-local-tools": "localtools",
    "open-internet": "open",
}
BLOCKED_ALWAYS_TOOLS = (
    "brew",
    "curl",
    "dtruss",
    "file",
    "gdb",
    "gh",
    "git",
    "hexdump",
    "lldb",
    "ltrace",
    "nm",
    "objdump",
    "otool",
    "perf",
    "readelf",
    "strings",
    "strace",
    "uv",
    "wget",
    "xxd",
)
SOURCE_ACQUISITION_GUARDS = {
    "apt": r"(^| )install( |$)|(^| )source( |$)",
    "apt-get": r"(^| )install( |$)|(^| )source( |$)",
    "cargo": r"(^| )(install|search|add|fetch|update|publish|login|owner|yank)( |$)",
    "go": r"(^| )(get|install)( |$)",
    "npm": r"(^| )(install|i|add|publish|login|view|info|search|pack)( |$)",
    "pip": r"(^| )install( |$)|(^| )download( |$)",
    "pip3": r"(^| )install( |$)|(^| )download( |$)",
    "pnpm": r"(^| )(install|i|add|publish|login|view|info|search|pack)( |$)",
    "yarn": r"(^| )(install|add|publish|login|info|search|pack)( |$)",
}
HOST_INSPECTION_GUARDS = (
    "cat",
    "find",
    "grep",
    "head",
    "ls",
    "rg",
    "sed",
    "tail",
    "wc",
)
HOST_INSPECTION_PATTERNS = (
    "/" + "Users" + "/",
    "/home/",
    "/Documents/" + "ProgramBench",
    "ProgramBench",
    "pb-goal-runs",
)
PARENT_TRAVERSAL_PATTERNS = (
    " .. ",
    "../",
    "/..",
)
TOOL_CACHE_ENV = (
    "CARGO_HOME",
    "CARGO_NET_OFFLINE",
    "GOMODCACHE",
    "GONOSUMDB",
    "GOPATH",
    "GOPROXY",
    "GOSUMDB",
    "NPM_CONFIG_CACHE",
    "NPM_CONFIG_OFFLINE",
    "PIP_CACHE_DIR",
    "PIP_NO_INDEX",
)
LOCAL_TOOLS_OFFLINE_ENV = (
    "CARGO_NET_OFFLINE",
    "GOPROXY",
    "GOSUMDB",
    "NPM_CONFIG_OFFLINE",
    "PIP_NO_INDEX",
)


def image_name(instance_id: str) -> str:
    return f"programbench/{instance_id.replace('__', '_1776_')}"


def slug(instance_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", instance_id).strip("-")


def model_slug(model: str) -> str:
    return slug(model.replace(".", ""))


def run_name(
    instance_id: str,
    model: str = DEFAULT_MODEL,
    reasoning_effort: str = DEFAULT_REASONING_EFFORT,
    inference_mode: str = DEFAULT_INFERENCE_MODE,
) -> str:
    name = instance_id.split("__", 1)[1].split(".", 1)[0] if "__" in instance_id else slug(instance_id)
    prefix = "gpt55" if model == DEFAULT_MODEL else model_slug(model)
    effort = "" if model == DEFAULT_MODEL and reasoning_effort == DEFAULT_REASONING_EFFORT else f"-{reasoning_effort}"
    return f"{prefix}-goal{effort}-{MODE_RUN_SEGMENTS[inference_mode]}-{name}"


def render_prompt(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def write_executable(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o755)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_guard_bin(
    guard_dir: Path,
    container_name: str,
    target_access: str,
    target_wrapper_command: str,
    allow_local_tools: bool,
) -> None:
    guard_dir.mkdir(parents=True, exist_ok=True)
    if target_access == "direct-docker":
        write_executable(
            guard_dir / "docker",
            f"""#!/usr/bin/env bash
set -euo pipefail
if [ "${{1:-}}" = "inspect" ] && [ "${{2:-}}" = {shlex.quote(container_name)} ]; then
  exec {shlex.quote(shutil.which("docker") or "docker")} "$@"
fi
if [ {str(allow_local_tools).lower()} = "true" ] && [ "${{1:-}}" = "cp" ]; then
  case "${{2:-}}" in
    {container_name}:/*)
      exec {shlex.quote(shutil.which("docker") or "docker")} "$@"
      ;;
  esac
fi
if [ {str(allow_local_tools).lower()} = "true" ] \\
  && [ "${{1:-}}" = "exec" ] \\
  && [ "${{2:-}}" = {shlex.quote(container_name)} ]; then
  exec {shlex.quote(shutil.which("docker") or "docker")} "$@"
fi
index=2
if [ "${{1:-}}" = "exec" ] && [ "${{2:-}}" = "-i" ]; then
  index=3
fi
if [ "$index" -eq 2 ]; then
  user_flag="${{2:-}}"
  user_name="${{3:-}}"
  target_container="${{4:-}}"
else
  user_flag="${{3:-}}"
  user_name="${{4:-}}"
  target_container="${{5:-}}"
fi
if [ "${{1:-}}" = "exec" ] \\
  && [ "$user_flag" = "-u" ] \\
  && [ "$user_name" = "agent" ] \\
  && [ "$target_container" = {shlex.quote(container_name)} ]; then
  exec {shlex.quote(shutil.which("docker") or "docker")} "$@"
fi
echo "blocked docker command. Use: docker exec [-i] -u agent {container_name} bash -lc '<command>'" >&2
exit 126
""",
        )
    else:
        write_executable(
            guard_dir / "docker",
            """#!/usr/bin/env bash
echo "blocked docker command. This run uses the configured target exec wrapper, not raw Docker." >&2
exit 126
""",
        )
    write_sudo_guard(guard_dir, container_name, target_access, target_wrapper_command)
    blocked_reason = (
        "host internet/source tooling" if allow_local_tools else "host internet/source/binary-analysis tooling"
    )
    for tool in BLOCKED_ALWAYS_TOOLS:
        if allow_local_tools and tool in {
            "dtruss",
            "file",
            "gdb",
            "hexdump",
            "lldb",
            "ltrace",
            "nm",
            "objdump",
            "otool",
            "perf",
            "readelf",
            "strings",
            "strace",
            "xxd",
        }:
            continue
        write_executable(
            guard_dir / tool,
            f"""#!/usr/bin/env bash
echo "blocked {tool}: ProgramBench cleanroom runs forbid {blocked_reason}" >&2
exit 126
""",
        )
    for tool, pattern in SOURCE_ACQUISITION_GUARDS.items():
        real = shutil.which(tool)
        exec_line = (
            f'exec {shlex.quote(real)} "$@"' if real else f'echo "{tool} is not available on this host" >&2\nexit 127'
        )
        write_executable(
            guard_dir / tool,
            f"""#!/usr/bin/env bash
set -euo pipefail
args=" $* "
blocked_re={shlex.quote(pattern)}
if [[ "$args" =~ $blocked_re ]]; then
  echo "blocked {tool}: ProgramBench cleanroom runs allow local builds, not source/package acquisition" >&2
  exit 126
fi
{exec_line}
""",
        )
    for tool in HOST_INSPECTION_GUARDS:
        real = shutil.which(tool)
        exec_line = (
            f'exec {shlex.quote(real)} "$@"' if real else f'echo "{tool} is not available on this host" >&2\nexit 127'
        )
        checks = "\n".join(
            [
                f'if [[ "$args" == *{shlex.quote(pattern)}* ]]; then '
                f'echo "blocked {tool}: ProgramBench cleanroom runs forbid host/evaluator path inspection" >&2; '
                "exit 126; fi"
                for pattern in (*HOST_INSPECTION_PATTERNS, *PARENT_TRAVERSAL_PATTERNS)
            ]
        )
        write_executable(
            guard_dir / tool,
            f"""#!/usr/bin/env bash
set -euo pipefail
args=" $* "
{checks}
{exec_line}
""",
        )


def write_sudo_guard(guard_dir: Path, container_name: str, target_access: str, target_wrapper_command: str) -> None:
    real_sudo = shutil.which("sudo") or "sudo"
    wrapper_parts = shlex.split(target_wrapper_command)
    if target_access == "wrapper" and wrapper_parts[:1] == ["sudo"]:
        allowed = wrapper_parts[1:] + [container_name]
        checks = "\n".join(
            f'[[ "${{{index}:-}}" == {shlex.quote(value)} ]] || allowed=0'
            for index, value in enumerate(allowed, start=1)
        )
        write_executable(
            guard_dir / "sudo",
            f"""#!/usr/bin/env bash
set -euo pipefail
allowed=1
[[ "$#" -ge {len(allowed)} ]] || allowed=0
{checks}
if [[ "$allowed" == 1 ]]; then
  exec {shlex.quote(real_sudo)} "$@"
fi
echo "blocked sudo command. Use only: {shlex.quote(target_wrapper_command)} {container_name} <command> [args...]" >&2
exit 126
""",
        )
        return
    write_executable(
        guard_dir / "sudo",
        """#!/usr/bin/env bash
echo "blocked sudo command in ProgramBench cleanroom run" >&2
exit 126
""",
    )


def tool_cache_exports(cache_dir: Path) -> str:
    values = {
        "CARGO_HOME": cache_dir / "cargo",
        "CARGO_NET_OFFLINE": "true",
        "GOMODCACHE": cache_dir / "go" / "pkg" / "mod",
        "GONOSUMDB": "*",
        "GOPATH": cache_dir / "go",
        "GOPROXY": "off",
        "GOSUMDB": "off",
        "NPM_CONFIG_CACHE": cache_dir / "npm",
        "NPM_CONFIG_OFFLINE": "true",
        "PIP_CACHE_DIR": cache_dir / "pip",
        "PIP_NO_INDEX": "1",
    }
    return " ".join(f"{key}={shlex.quote(str(value))}" for key, value in values.items())


def local_tools_offline_exports() -> str:
    values = {
        "CARGO_NET_OFFLINE": "true",
        "GOPROXY": "off",
        "GOSUMDB": "off",
        "NPM_CONFIG_OFFLINE": "true",
        "PIP_NO_INDEX": "1",
    }
    return " ".join(f"{key}={shlex.quote(value)}" for key, value in values.items())


def strict_paper_compliant(args: argparse.Namespace) -> bool:
    return (
        args.inference_mode == "paper"
        and args.target_access == "wrapper"
        and platform.system() == "Linux"
        and platform.machine() in {"x86_64", "AMD64"}
        and str(args.docker_cpus) == "20"
        and args.docker_memory == "60g"
    )


def prepare(args: argparse.Namespace) -> None:
    if args.inference_mode == "paper" and args.target_access != "wrapper":
        raise SystemExit("paper mode requires --target-access wrapper; use no-internet for direct-docker ablations")
    root = Path(args.run_root).expanduser().resolve()
    prepared_run_name = args.run_name or run_name(
        args.instance_id,
        args.model,
        args.reasoning_effort,
        args.inference_mode,
    )
    instance_dir = root / prepared_run_name / args.instance_id
    solution_dir = instance_dir / "solution"
    guard_dir = instance_dir / "guard-bin"
    cache_dir = instance_dir / "tool-caches"
    paper_mode = args.inference_mode == "paper"
    cleanroom_mode = args.inference_mode in {"paper", "no-internet"}
    local_tools_mode = args.inference_mode == "no-internet-local-tools"
    no_internet_mode = args.inference_mode in {"paper", "no-internet", "no-internet-local-tools"}
    tool_env = list(TOOL_CACHE_ENV) if cleanroom_mode else list(LOCAL_TOOLS_OFFLINE_ENV) if local_tools_mode else []
    container_name = f"pb-goal-{slug(prepared_run_name)}-{slug(args.instance_id)}"
    session_name = f"pb-goal-{slug(prepared_run_name)}-{slug(args.instance_id)}"
    image = image_name(args.instance_id)
    target_command = (
        f"docker exec {container_name} bash -lc '<command>'"
        if local_tools_mode and args.target_access == "direct-docker"
        else (
            f"docker exec -u agent {container_name} bash -lc '<command>'"
            if args.target_access == "direct-docker"
            else f"{args.target_wrapper_command} {container_name} bash -lc '<command>'"
        )
    )
    objective = (
        f"Solve ProgramBench instance {args.instance_id} in the cleanroom container by reimplementing the "
        "target CLI from black-box behavior only. Do not mark the goal complete until solution/compile.sh exists, "
        "running ./compile.sh creates ./executable, and package-submission succeeds. Do not inspect parent "
        "directories or files outside the solution directory."
    )

    solution_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    write_guard_bin(guard_dir, container_name, args.target_access, args.target_wrapper_command, local_tools_mode)
    (solution_dir / "AGENT_RULES.md").write_text(
        (
            "Do not use internet, package managers, upstream source, decompilers, "
            "disassemblers, tracing/instrumentation tools, ProgramBench tests, or "
            "the ProgramBench evaluator repository. Do not inspect files outside "
            "this solution directory, do not run commands against '..', and do not inspect parent directories. "
            "The harness helper is exposed only as the package-submission command. Probe the "
            f"target executable at /workspace/executable with {target_command}. "
            "Use only documentation already present in the cleanroom container.\n"
        )
        if cleanroom_mode
        else (
            "No-internet local-tools research mode: this is not ProgramBench-compliant and must not be reported as a "
            "cleanroom benchmark result. Do not use internet, package registries, public source, external docs, or "
            "ProgramBench tests. Local installed tools, binary-analysis tools, tracing tools, and agent-created tools "
            f"are allowed. Probe the target executable at /workspace/executable with {target_command}.\n"
        )
        if local_tools_mode
        else (
            "Open-internet research mode: this is not ProgramBench-compliant and must not be reported as a cleanroom "
            "benchmark result. You may use internet/package tooling to solve the task, but still write a packageable "
            f"solution and probe the target executable at /workspace/executable with {target_command}.\n"
        )
    )
    prompt_template = (
        args.prompt_template
        or {
            "paper": PROMPT_TEMPLATE,
            "no-internet": NO_INTERNET_PROMPT_TEMPLATE,
            "no-internet-local-tools": LOCAL_TOOLS_PROMPT_TEMPLATE,
            "open-internet": OPEN_PROMPT_TEMPLATE,
        }[args.inference_mode]
    )
    prompt_template_path = Path(prompt_template).expanduser()
    (instance_dir / "GOAL_PROMPT.md").write_text(
        render_prompt(
            prompt_template_path.read_text(),
            {
                "instance_id": args.instance_id,
                "run_name": prepared_run_name,
                "image": image,
                "container_name": container_name,
                "solution_dir": str(solution_dir),
                "target_command": target_command,
                "package_command": "package-submission",
            },
        )
    )
    (instance_dir / "GOAL_OBJECTIVE.txt").write_text(objective + "\n")
    (instance_dir / "run.json").write_text(
        json.dumps(
            {
                "instance_id": args.instance_id,
                "run_name": prepared_run_name,
                "image": image,
                "container_name": container_name,
                "session_name": session_name,
                "solution_dir": str(solution_dir),
                "guard_bin_dir": str(guard_dir),
                "tool_cache_dir": str(cache_dir),
                "tool_cache_env": tool_env,
                "target_access": args.target_access,
                "target_wrapper_command": args.target_wrapper_command,
                "target_command": target_command,
                "prompt_template": str(prompt_template_path),
                "prompt_template_sha256": file_sha256(prompt_template_path),
                "prompt_rendered_sha256": file_sha256(instance_dir / "GOAL_PROMPT.md"),
                "docker_cpus": args.docker_cpus,
                "docker_memory": args.docker_memory,
                "inference_mode": args.inference_mode,
                "paper_mode": paper_mode,
                "paper_compliant": strict_paper_compliant(args),
                "model": args.model,
                "reasoning_effort": args.reasoning_effort,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "host_machine": platform.machine(),
                "host_system": platform.system(),
            },
            indent=2,
        )
        + "\n"
    )

    network_check = (
        f'test "$(docker inspect {shlex.quote(container_name)} --format \'{{{{.HostConfig.NetworkMode}}}}\')" = "none"'
        if no_internet_mode
        else "echo 'open-internet mode: target container network is intentionally not cleanroom-compliant'"
    )
    network_arg = "--network none" if no_internet_mode else "--network bridge"
    write_executable(
        instance_dir / "start-target.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
docker rm -f {shlex.quote(container_name)} >/dev/null 2>&1 || true
docker pull --platform linux/amd64 {shlex.quote(image)}:task_cleanroom
docker run -d --platform linux/amd64 \\
  --name {shlex.quote(container_name)} \\
  {network_arg} \\
  --cpus {shlex.quote(str(args.docker_cpus))} \\
  --memory {shlex.quote(args.docker_memory)} \\
  -v {shlex.quote(str(solution_dir))}:/workspace/solution \\
  {shlex.quote(image)}:task_cleanroom \\
  sleep infinity
docker exec -u agent {shlex.quote(container_name)} bash -lc 'pwd; find /workspace -maxdepth 2 -type f | sort | head -80'
""",
    )
    write_executable(
        instance_dir / "check-compliance.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
docker inspect {shlex.quote(container_name)} \\
  --format 'network={{{{.HostConfig.NetworkMode}}}} image={{{{.Config.Image}}}} status={{{{.State.Status}}}}'
{network_check}
docker exec -u agent {shlex.quote(container_name)} bash -lc '
  set -e
  id
  stat -c "%A %a %U %G %n" /workspace/executable
  test -x /workspace/executable
  if head -c 4 /workspace/executable >/tmp/pb-readtest 2>/dev/null; then
    echo "FAIL executable is readable"
    exit 1
  fi
  if strings /workspace/executable >/tmp/pb-stringtest 2>/dev/null; then
    echo "FAIL strings can read executable"
    exit 1
  fi
  if objdump -h /workspace/executable >/tmp/pb-objdumptest 2>/dev/null; then
    echo "FAIL objdump can read executable"
    exit 1
  fi
  echo "ok: agent can execute but cannot read/decompile executable"
'
(
  cd {shlex.quote(str(solution_dir))}
  export PATH={shlex.quote(str(guard_dir))}:$PATH
  command -v package-submission >/dev/null
  if rg --files -uu .. >/tmp/pb-parent-guard.out 2>/tmp/pb-parent-guard.err; then
    echo "FAIL guard allowed parent-directory inspection" >&2
    exit 1
  fi
  grep -q "blocked rg" /tmp/pb-parent-guard.err
  echo "ok: guard blocks parent-directory inspection and exposes package-submission"
)
""",
    )
    codex_env = (
        f"PATH={shlex.quote(str(guard_dir))}:$PATH GIT_CEILING_DIRECTORIES={shlex.quote(str(instance_dir))} "
        f"{tool_cache_exports(cache_dir)}"
        if cleanroom_mode
        else (
            f"PATH={shlex.quote(str(guard_dir))}:$PATH GIT_CEILING_DIRECTORIES={shlex.quote(str(instance_dir))} "
            f"{local_tools_offline_exports()}"
        )
        if local_tools_mode
        else f"GIT_CEILING_DIRECTORIES={shlex.quote(str(instance_dir))}"
    )
    write_executable(
        instance_dir / "start-codex-goal.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
CODEX_BYPASS_FLAG="--yolo"
if ! codex --yolo --version >/dev/null 2>&1; then
  CODEX_BYPASS_FLAG="--dangerously-bypass-approvals-and-sandbox"
fi
CODEX_CONFIG="${{CODEX_HOME:-$HOME/.codex}}/config.toml"
TRUST_KEY="$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' {shlex.quote(str(solution_dir))})"
mkdir -p "$(dirname "$CODEX_CONFIG")"
if ! grep -Fqx "[projects.$TRUST_KEY]" "$CODEX_CONFIG" 2>/dev/null; then
  {{
    printf '\\n[projects.%s]\\n' "$TRUST_KEY"
    printf 'trust_level = "trusted"\\n'
  }} >> "$CODEX_CONFIG"
fi
tmux kill-session -t {shlex.quote(session_name)} >/dev/null 2>&1 || true
tmux new-session -d -s {shlex.quote(session_name)} -c {shlex.quote(str(solution_dir))} \\
  "{codex_env} codex --enable goals --disable plugins --disable apps -m {shlex.quote(args.model)} \\
  -c model_reasoning_effort={shlex.quote(args.reasoning_effort)} \\
  -c trust_level=trusted \\
  -C {shlex.quote(str(solution_dir))} $CODEX_BYPASS_FLAG --no-alt-screen"
tmux pipe-pane -o -t {shlex.quote(session_name)} 'cat >> {shlex.quote(str(instance_dir / "tmux-transcript.log"))}'
sleep 4
tmux send-keys -t {shlex.quote(session_name)} {shlex.quote("/goal " + objective)} Enter
sleep 2
tmux load-buffer {shlex.quote(str(instance_dir / "GOAL_PROMPT.md"))}
tmux paste-buffer -t {shlex.quote(session_name)}
tmux send-keys -t {shlex.quote(session_name)} Enter
echo "Attached session: tmux attach -t {session_name}"
""",
    )
    write_executable(
        instance_dir / "package-submission.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
test -f {shlex.quote(str(solution_dir / "compile.sh"))} || {{
  echo "missing solution/compile.sh" >&2
  exit 1
}}
COPYFILE_DISABLE=1 tar -C {shlex.quote(str(solution_dir))} \\
  --exclude './AGENT_RULES.md' \\
  --exclude './.DS_Store' \\
  --exclude './._*' \\
  -czf {shlex.quote(str(instance_dir / "submission.tar.gz"))} .
/bin/ls -lh {shlex.quote(str(instance_dir / "submission.tar.gz"))}
""",
    )
    write_executable(
        guard_dir / "package-submission",
        f"""#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *".."* ]]; then
  echo "blocked package-submission: parent traversal is not allowed" >&2
  exit 126
fi
exec {shlex.quote(str(instance_dir / "package-submission.sh"))} "$@"
""",
    )
    write_executable(
        instance_dir / "eval-submission.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
programbench_repo="${{1:?usage: $0 /path/to/ProgramBench}}"
cd "$programbench_repo"
uv run programbench eval {shlex.quote(str(instance_dir.parent))} \\
  --filter {shlex.quote(args.instance_id)} \\
  --workers 1 \\
  --branch-workers 2 \\
  --docker-cpus {shlex.quote(str(args.docker_cpus))}
uv run programbench info {shlex.quote(str(instance_dir.parent))}
""",
    )

    print(instance_dir)
    if platform.machine() not in {"x86_64", "AMD64"}:
        print("warning: this host is not amd64; use a Linux amd64 host for real runs")


def prepare_batch(args: argparse.Namespace) -> None:
    for line in Path(args.target_file).expanduser().read_text().splitlines():
        instance_id = line.split("#", 1)[0].strip()
        if instance_id:
            prepare(
                argparse.Namespace(
                    instance_id=instance_id,
                    run_root=args.run_root,
                    run_name="",
                    prompt_template=args.prompt_template,
                    target_access=args.target_access,
                    target_wrapper_command=args.target_wrapper_command,
                    docker_cpus=args.docker_cpus,
                    docker_memory=args.docker_memory,
                    inference_mode=args.inference_mode,
                    model=args.model,
                    reasoning_effort=args.reasoning_effort,
                )
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare Codex /goal ProgramBench runs")
    subparsers = parser.add_subparsers(required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("instance_id")
    prepare_parser.add_argument("--run-root", default=str(DEFAULT_ROOT))
    prepare_parser.add_argument("--run-name", default="")
    prepare_parser.add_argument("--docker-cpus", type=int, default=20)
    prepare_parser.add_argument("--docker-memory", default="60g")
    prepare_parser.add_argument(
        "--inference-mode",
        choices=["paper", "no-internet", "no-internet-local-tools", "open-internet"],
        default=DEFAULT_INFERENCE_MODE,
    )
    prepare_parser.add_argument(
        "--target-access",
        choices=["direct-docker", "wrapper"],
        default="direct-docker",
        help="Use guarded raw Docker for local smoke runs, or a narrow external target exec wrapper for strict runs.",
    )
    prepare_parser.add_argument("--target-wrapper-command", default="sudo -n /usr/local/bin/pb-target-exec")
    prepare_parser.add_argument("--model", default=DEFAULT_MODEL)
    prepare_parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT)
    prepare_parser.add_argument(
        "--prompt-template",
        default="",
        help="Prompt template to render. Use this to pass an official ProgramBench prompt unchanged when available.",
    )
    prepare_parser.set_defaults(func=prepare)
    batch_parser = subparsers.add_parser("prepare-batch")
    batch_parser.add_argument("target_file")
    batch_parser.add_argument("--run-root", default=str(DEFAULT_ROOT))
    batch_parser.add_argument("--docker-cpus", type=int, default=20)
    batch_parser.add_argument("--docker-memory", default="60g")
    batch_parser.add_argument(
        "--inference-mode",
        choices=["paper", "no-internet", "no-internet-local-tools", "open-internet"],
        default=DEFAULT_INFERENCE_MODE,
    )
    batch_parser.add_argument(
        "--target-access",
        choices=["direct-docker", "wrapper"],
        default="direct-docker",
        help="Use guarded raw Docker for local smoke runs, or a narrow external target exec wrapper for strict runs.",
    )
    batch_parser.add_argument("--target-wrapper-command", default="sudo -n /usr/local/bin/pb-target-exec")
    batch_parser.add_argument("--model", default=DEFAULT_MODEL)
    batch_parser.add_argument("--reasoning-effort", default=DEFAULT_REASONING_EFFORT)
    batch_parser.add_argument(
        "--prompt-template",
        default="",
        help="Prompt template to render. Use this to pass an official ProgramBench prompt unchanged when available.",
    )
    batch_parser.set_defaults(func=prepare_batch)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
