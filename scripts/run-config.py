#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from itertools import chain
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
RUN_BATCH = REPO / "scripts" / "run-batch.py"


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def option_args(name: str, value: Any) -> list[str]:
    return [] if value == "" or value is None else [f"--{name.replace('_', '-')}", str(value)]


def flag_args(name: str, value: bool) -> list[str]:
    return [f"--{name.replace('_', '-')}"] if value else []


def run_version(config: dict[str, Any]) -> str:
    return os.environ.get("RUN_VERSION") or str(config.get("run_version") or "")


def common_watch_args(config: dict[str, Any], args: argparse.Namespace) -> list[str]:
    names = (
        "run_root",
        "poll_seconds",
        "docker_cpus",
        "docker_memory",
        "inference_mode",
        "target_access",
        "target_wrapper_command",
        "model",
        "reasoning_effort",
        "run_name_prefix",
        "min_goal_seconds",
        "min_goal_calls",
        "max_goal_continuations",
    )
    return [
        sys.executable,
        str(RUN_BATCH),
        "watch",
        config["target_file"],
        "--batch-name",
        config["batch_name"],
        *option_args("run_version", run_version(config)),
        *option_args(
            "max_parallel",
            args.max_parallel if args.max_parallel is not None else config.get("max_parallel"),
        ),
        *chain.from_iterable(option_args(name, config.get(name)) for name in names),
        *flag_args("strict_egress", bool(config.get("strict_egress"))),
    ]


def command(config: dict[str, Any], args: argparse.Namespace) -> list[str]:
    if args.action == "watch":
        return [*common_watch_args(config, args), *flag_args("once", args.once)]
    if args.action == "status":
        return [
            sys.executable,
            str(RUN_BATCH),
            "status",
            "--batch-name",
            config["batch_name"],
            *option_args("run_version", run_version(config)),
        ]
    return [
        sys.executable,
        str(RUN_BATCH),
        "finalize",
        "--batch-name",
        config["batch_name"],
        *option_args("run_version", run_version(config)),
        *option_args("programbench_repo", args.programbench_repo or config.get("programbench_repo")),
        *option_args("eval_timeout_seconds", config.get("eval_timeout_seconds")),
        *option_args("limit", args.limit),
        *flag_args("strict_paper", bool(config.get("strict_paper"))),
        *flag_args("allow_partial", args.allow_partial),
        *flag_args("retry_finalize_failed", args.retry_finalize_failed),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a named ProgramBench /goal batch config")
    parser.add_argument("action", choices=["watch", "status", "finalize"])
    parser.add_argument("config")
    parser.add_argument("--once", action="store_true", help="only applies to watch")
    parser.add_argument("--max-parallel", type=int, default=None, help="override config max_parallel for watch")
    parser.add_argument("--programbench-repo", default="", help="only applies to finalize")
    parser.add_argument("--allow-partial", action="store_true", help="only applies to finalize")
    parser.add_argument("--retry-finalize-failed", action="store_true", help="only applies to finalize")
    parser.add_argument("--limit", type=int, default=0, help="only applies to finalize")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cmd = command(load_config(Path(args.config)), args)
    if args.dry_run:
        print(shlex.join(cmd))
        return
    subprocess.run(cmd, cwd=REPO, check=True)


if __name__ == "__main__":
    main()
