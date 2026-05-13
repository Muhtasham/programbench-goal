#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_ROOT = Path.home() / "pb-goal-runs"
DEFAULT_STATE_ROOT = REPO / "local_state" / "batches"
DONE_MARKERS = ("Goal achieved", "Goal marked complete")
RATE_LIMIT_MARKERS = ("rate limit", "rate_limit", "429")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_targets(path: Path) -> list[str]:
    return [line.split("#", 1)[0].strip() for line in path.read_text().splitlines() if line.split("#", 1)[0].strip()]


def state_path(batch_name: str) -> Path:
    return DEFAULT_STATE_ROOT / f"{batch_name}.json"


def load_state(batch_name: str) -> dict:
    path = state_path(batch_name)
    return (
        json.loads(path.read_text())
        if path.is_file()
        else {
            "batch_name": batch_name,
            "created_at": now(),
            "updated_at": now(),
            "items": {},
        }
    )


def save_state(state: dict) -> None:
    path = state_path(state["batch_name"])
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = now()
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def run(cmd: list[str], cwd: Path = REPO, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=check)


def tmux_has_session(session: str) -> bool:
    return (
        subprocess.run(
            ["tmux", "has-session", "-t", session], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode
        == 0
    )


def tmux_capture(session: str) -> str:
    if not tmux_has_session(session):
        return ""
    return run(["tmux", "capture-pane", "-pt", session, "-S", "-220"], check=False).stdout


def prepare_instance(args: argparse.Namespace, instance_id: str, run_root: Path) -> dict:
    cmd = [
        sys.executable,
        str(REPO / "programbench_goal_runner.py"),
        "prepare",
        instance_id,
        "--run-root",
        str(run_root),
        "--docker-cpus",
        str(args.docker_cpus),
        "--docker-memory",
        args.docker_memory,
        "--inference-mode",
        args.inference_mode,
        "--target-access",
        args.target_access,
        "--target-wrapper-command",
        args.target_wrapper_command,
        "--model",
        args.model,
        "--reasoning-effort",
        args.reasoning_effort,
    ]
    if args.run_name_prefix:
        cmd.extend(["--run-name", f"{args.run_name_prefix}-{instance_id.replace('__', '-').split('.', 1)[0]}"])
    output = run(cmd).stdout.splitlines()
    instance_dir = Path(next(line for line in output if line.startswith("/"))).resolve()
    run_json = json.loads((instance_dir / "run.json").read_text())
    return {
        "instance_id": instance_id,
        "status": "prepared",
        "instance_dir": str(instance_dir),
        "run_name": run_json["run_name"],
        "session_name": run_json["session_name"],
        "container_name": run_json["container_name"],
        "prepared_at": now(),
        "last_error": "",
    }


def start_instance(record: dict) -> dict:
    instance_dir = Path(record["instance_dir"])
    run([str(instance_dir / "start-target.sh")])
    run([str(instance_dir / "check-compliance.sh")])
    run([str(instance_dir / "start-codex-goal.sh")])
    return {**record, "status": "running", "started_at": now(), "last_error": ""}


def refresh_record(record: dict) -> dict:
    if record["status"] != "running":
        return record
    pane = tmux_capture(record["session_name"])
    if any(marker in pane for marker in DONE_MARKERS):
        return {**record, "status": "goal_done", "goal_done_at": now(), "last_pane_tail": pane[-4000:]}
    if pane and any(marker in pane.lower() for marker in RATE_LIMIT_MARKERS):
        return {**record, "last_rate_limit_seen_at": now(), "last_pane_tail": pane[-4000:]}
    if not tmux_has_session(record["session_name"]):
        return {**record, "status": "failed", "failed_at": now(), "last_error": "tmux session ended before goal_done"}
    return {**record, "last_pane_tail": pane[-4000:]}


def update_targets(state: dict, targets: list[str]) -> None:
    for instance_id in targets:
        state["items"].setdefault(instance_id, {"instance_id": instance_id, "status": "pending", "last_error": ""})


def running_count(state: dict) -> int:
    return sum(record["status"] == "running" for record in state["items"].values())


def active_rate_limit(state: dict) -> bool:
    return any(
        record.get("last_rate_limit_seen_at") and record["status"] == "running" for record in state["items"].values()
    )


def launch_ready(args: argparse.Namespace, state: dict, run_root: Path) -> None:
    if active_rate_limit(state):
        return
    for instance_id, record in state["items"].items():
        if running_count(state) >= args.max_parallel:
            return
        if record["status"] != "pending":
            continue
        try:
            state["items"][instance_id] = start_instance(prepare_instance(args, instance_id, run_root))
        except subprocess.CalledProcessError as e:
            state["items"][instance_id] = {
                **record,
                "status": "failed",
                "failed_at": now(),
                "last_error": e.stdout[-4000:],
            }
        save_state(state)


def refresh_state(state: dict) -> None:
    for instance_id, record in list(state["items"].items()):
        state["items"][instance_id] = refresh_record(record)


def summarize_state(state: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in state["items"].values():
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    return counts


def print_status(state: dict) -> None:
    counts = summarize_state(state)
    print(",".join(f"{key}={counts[key]}" for key in sorted(counts)))
    for record in state["items"].values():
        print(
            ",".join(
                [
                    record["instance_id"],
                    record["status"],
                    record.get("run_name", ""),
                    record.get("session_name", ""),
                    record.get("last_error", "").replace("\n", "\\n")[:240],
                ]
            )
        )


def watch(args: argparse.Namespace) -> None:
    state = load_state(args.batch_name)
    update_targets(state, read_targets(Path(args.target_file).expanduser()))
    run_root = Path(args.run_root).expanduser() if args.run_root else DEFAULT_RUNS_ROOT / args.batch_name
    state["run_root"] = str(run_root)
    while True:
        refresh_state(state)
        launch_ready(args, state, run_root)
        save_state(state)
        print_status(state)
        if args.once:
            return
        if all(
            record["status"] in {"goal_done", "packaged", "evaluated", "failed"} for record in state["items"].values()
        ):
            return
        time.sleep(args.poll_seconds)


def status(args: argparse.Namespace) -> None:
    state = load_state(args.batch_name)
    refresh_state(state)
    save_state(state)
    print_status(state)


def finalize_one(args: argparse.Namespace, record: dict) -> dict:
    instance_dir = Path(record["instance_dir"])
    try:
        run([str(instance_dir / "package-submission.sh")])
        audit_cmd = [sys.executable, str(REPO / "scripts" / "audit-run.py")]
        if args.strict_paper:
            audit_cmd.append("--strict-paper")
        audit_cmd.append(str(instance_dir))
        run(audit_cmd)
        if args.programbench_repo:
            run([str(instance_dir / "eval-submission.sh"), str(Path(args.programbench_repo).expanduser())])
            return {**record, "status": "evaluated", "evaluated_at": now(), "last_error": ""}
        return {**record, "status": "packaged", "packaged_at": now(), "last_error": ""}
    except subprocess.CalledProcessError as e:
        return {**record, "status": "failed", "failed_at": now(), "last_error": e.stdout[-4000:]}


def summarize_and_collect(args: argparse.Namespace, state: dict) -> None:
    if not args.programbench_repo:
        return
    run_root = Path(state["run_root"])
    output = DEFAULT_STATE_ROOT / state["batch_name"] / "results.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "uv",
            "run",
            "--project",
            str(Path(args.programbench_repo).expanduser()),
            "python",
            str(REPO / "scripts" / "summarize-results.py"),
            str(run_root),
            "--programbench-repo",
            str(Path(args.programbench_repo).expanduser()),
            "--output",
            str(output),
        ]
    )
    for record in state["items"].values():
        if record["status"] == "evaluated":
            run(
                [
                    sys.executable,
                    str(REPO / "scripts" / "collect-run-artifacts.py"),
                    record["instance_dir"],
                    "--results-csv",
                    str(output),
                ]
            )
    print(output)


def finalize(args: argparse.Namespace) -> None:
    state = load_state(args.batch_name)
    refresh_state(state)
    for instance_id, record in list(state["items"].items()):
        if record["status"] == "goal_done":
            state["items"][instance_id] = finalize_one(args, record)
            save_state(state)
    summarize_and_collect(args, state)
    save_state(state)
    print_status(state)


def add_common_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--batch-name", required=True)
    parser.add_argument("--run-root", default="")
    parser.add_argument("--max-parallel", type=int, default=1)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--docker-cpus", type=int, default=20)
    parser.add_argument("--docker-memory", default="60g")
    parser.add_argument(
        "--inference-mode",
        choices=["paper", "no-internet", "no-internet-local-tools", "open-internet"],
        default="paper",
    )
    parser.add_argument("--target-access", choices=["direct-docker", "wrapper"], default="direct-docker")
    parser.add_argument("--target-wrapper-command", default="sudo -n /usr/local/bin/pb-target-exec")
    parser.add_argument("--model", default="gpt-5.5")
    parser.add_argument("--reasoning-effort", default="xhigh")
    parser.add_argument("--run-name-prefix", default="")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ProgramBench /goal batches with local resumable state")
    subparsers = parser.add_subparsers(required=True)

    watch_parser = subparsers.add_parser("watch")
    watch_parser.add_argument("target_file")
    watch_parser.add_argument("--once", action="store_true")
    add_common_run_args(watch_parser)
    watch_parser.set_defaults(func=watch)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--batch-name", required=True)
    status_parser.set_defaults(func=status)

    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--batch-name", required=True)
    finalize_parser.add_argument("--programbench-repo", default="")
    finalize_parser.add_argument("--strict-paper", action="store_true")
    finalize_parser.set_defaults(func=finalize)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
