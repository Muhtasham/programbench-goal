#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import re
import shlex
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_ROOT = Path.home() / "pb-goal-runs"
PROMPT_TEMPLATE = Path(__file__).parent / "prompts" / "programbench_goal.md"


def image_name(instance_id: str) -> str:
    return f"programbench/{instance_id.replace('__', '_1776_')}"


def slug(instance_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", instance_id).strip("-")


def run_name(instance_id: str) -> str:
    name = instance_id.split("__", 1)[1].split(".", 1)[0] if "__" in instance_id else slug(instance_id)
    return f"gpt55-goal-{name}"


def render_prompt(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def write_executable(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o755)


def prepare(args: argparse.Namespace) -> None:
    root = Path(args.run_root).expanduser().resolve()
    instance_dir = root / (args.run_name or run_name(args.instance_id)) / args.instance_id
    solution_dir = instance_dir / "solution"
    container_name = f"pb-goal-{slug(args.instance_id)}"
    session_name = f"pb-goal-{slug(args.instance_id)}"
    image = image_name(args.instance_id)
    objective = (
        f"Solve ProgramBench instance {args.instance_id} in the cleanroom container by reimplementing the "
        "target CLI from black-box behavior only, then produce a packageable submission."
    )

    solution_dir.mkdir(parents=True, exist_ok=True)
    (solution_dir / "AGENT_RULES.md").write_text(
        "Do not use internet, package managers, upstream source, decompilers, "
        "ProgramBench tests, or the ProgramBench evaluator repository. Probe the "
        f"target with docker exec -u agent {container_name} bash -lc '<command>'. "
        "Use only documentation already present in the cleanroom container.\n"
    )
    (instance_dir / "GOAL_PROMPT.md").write_text(
        render_prompt(
            Path(args.prompt_template).expanduser().read_text(),
            {
                "instance_id": args.instance_id,
                "image": image,
                "container_name": container_name,
                "solution_dir": str(solution_dir),
            },
        )
    )
    (instance_dir / "GOAL_OBJECTIVE.txt").write_text(objective + "\n")
    (instance_dir / "run.json").write_text(
        json.dumps(
            {
                "instance_id": args.instance_id,
                "image": image,
                "container_name": container_name,
                "session_name": session_name,
                "solution_dir": str(solution_dir),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "host_machine": platform.machine(),
                "host_system": platform.system(),
            },
            indent=2,
        )
        + "\n"
    )

    write_executable(
        instance_dir / "start-target.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
docker rm -f {shlex.quote(container_name)} >/dev/null 2>&1 || true
docker pull --platform linux/amd64 {shlex.quote(image)}:task_cleanroom
docker run -d --platform linux/amd64 \\
  --name {shlex.quote(container_name)} \\
  --network none \\
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
docker inspect {shlex.quote(container_name)} --format 'network={{{{.HostConfig.NetworkMode}}}} image={{{{.Config.Image}}}} status={{{{.State.Status}}}}'
test "$(docker inspect {shlex.quote(container_name)} --format '{{{{.HostConfig.NetworkMode}}}}')" = "none"
docker exec -u agent {shlex.quote(container_name)} bash -lc '
  set -e
  id
  stat -c "%A %a %U %G %n" /workspace/executable
  /workspace/executable --version >/dev/null
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
""",
    )
    write_executable(
        instance_dir / "start-codex-goal.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
tmux kill-session -t {shlex.quote(session_name)} >/dev/null 2>&1 || true
tmux new-session -d -s {shlex.quote(session_name)} -c {shlex.quote(str(solution_dir))} \\
  "codex --enable goals -m gpt-5.5 -c model_reasoning_effort='xhigh' -C {shlex.quote(str(solution_dir))} -s danger-full-access -a never --no-alt-screen"
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
tar -C {shlex.quote(str(solution_dir))} -czf {shlex.quote(str(instance_dir / "submission.tar.gz"))} .
ls -lh {shlex.quote(str(instance_dir / "submission.tar.gz"))}
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
  --docker-cpus 8
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
                )
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare Codex /goal ProgramBench runs")
    subparsers = parser.add_subparsers(required=True)
    prepare_parser = subparsers.add_parser("prepare")
    prepare_parser.add_argument("instance_id")
    prepare_parser.add_argument("--run-root", default=str(DEFAULT_ROOT))
    prepare_parser.add_argument("--run-name", default="")
    prepare_parser.add_argument(
        "--prompt-template",
        default=str(PROMPT_TEMPLATE),
        help="Prompt template to render. Use this to pass an official ProgramBench prompt unchanged when available.",
    )
    prepare_parser.set_defaults(func=prepare)
    batch_parser = subparsers.add_parser("prepare-batch")
    batch_parser.add_argument("target_file")
    batch_parser.add_argument("--run-root", default=str(DEFAULT_ROOT))
    batch_parser.add_argument(
        "--prompt-template",
        default=str(PROMPT_TEMPLATE),
        help="Prompt template to render. Use this to pass an official ProgramBench prompt unchanged when available.",
    )
    batch_parser.set_defaults(func=prepare_batch)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
