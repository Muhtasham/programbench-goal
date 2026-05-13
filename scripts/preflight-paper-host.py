#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FORBIDDEN_GUARD_TOOLS = (
    "curl",
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
    "wget",
    "xxd",
)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    strict: bool = True


def run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=check)


def docker_info() -> dict:
    result = run(["docker", "info", "--format", "{{json .}}"])
    return json.loads(result.stdout) if result.returncode == 0 else {}


def docker_memory_gib(info: dict) -> float:
    return int(info.get("MemTotal") or 0) / (1024**3)


def user_groups(user: str) -> set[str]:
    result = run(["id", "-nG", user])
    return set(result.stdout.split()) if result.returncode == 0 else set()


def egress_status(user: str) -> tuple[bool, str]:
    script = REPO / "scripts" / "linux-openai-egress-guard.sh"
    cmd = [str(script), "status", user] if os.geteuid() == 0 else ["sudo", "-n", str(script), "status", user]
    result = run(cmd)
    return result.returncode == 0 and "PB_OPENAI_" in result.stdout, result.stdout[-1200:]


def container_network(container: str) -> str:
    result = run(["docker", "inspect", container, "--format", "{{.HostConfig.NetworkMode}}"])
    return result.stdout.strip() if result.returncode == 0 else ""


def sudoers_allows_wrapper(wrapper: str) -> tuple[bool, str]:
    if os.geteuid() == 0:
        return True, "running as root"
    if not shutil.which("sudo"):
        return False, "sudo not installed"
    result = run(["sudo", "-n", "-l", wrapper])
    return result.returncode == 0, result.stdout[-1200:]


def check_instance(instance_dir: Path) -> list[Check]:
    run_json = json.loads((instance_dir / "run.json").read_text())
    guard_dir = Path(run_json["guard_bin_dir"])
    checks = [
        Check("instance inference mode", run_json.get("inference_mode") == "paper", run_json.get("inference_mode", "")),
        Check("target access wrapper", run_json.get("target_access") == "wrapper", run_json.get("target_access", "")),
        Check(
            "target container network",
            container_network(run_json["container_name"]) == "none",
            container_network(run_json["container_name"]) or "container not running",
        ),
        Check("guard bin exists", guard_dir.is_dir(), str(guard_dir)),
    ]
    for tool in FORBIDDEN_GUARD_TOOLS:
        checks.append(Check(f"guard blocks {tool}", (guard_dir / tool).is_file(), str(guard_dir / tool)))
    return checks


def collect(args: argparse.Namespace) -> list[Check]:
    info = docker_info() if shutil.which("docker") else {}
    checks = [
        Check("host system", platform.system() == "Linux", platform.system()),
        Check("host machine", platform.machine() in {"x86_64", "AMD64"}, platform.machine()),
        Check("docker available", bool(info), "docker info succeeded" if info else "docker info failed"),
        Check("docker cpus", int(info.get("NCPU") or 0) >= args.min_cpus, str(info.get("NCPU", ""))),
        Check("docker memory", docker_memory_gib(info) >= args.min_memory_gib, f"{docker_memory_gib(info):.1f} GiB"),
        Check("codex user exists", run(["id", "-u", args.codex_user]).returncode == 0, args.codex_user),
    ]
    groups = user_groups(args.codex_user)
    checks.append(
        Check(
            "codex user lacks docker group",
            "docker" not in groups or args.allow_direct_docker,
            ",".join(sorted(groups)) or "no groups",
        )
    )
    if args.check_egress_guard:
        ok, detail = egress_status(args.codex_user)
        checks.append(Check("OpenAI egress guard installed", ok, detail.strip() or "no status output"))
    if args.wrapper_command:
        wrapper = args.wrapper_command.split()[-1]
        checks.append(Check("target exec wrapper installed", Path(wrapper).is_file(), wrapper))
        ok, detail = sudoers_allows_wrapper(wrapper)
        checks.append(Check("sudoers allows target wrapper", ok, detail.strip() or wrapper))
    if args.instance_dir:
        checks.extend(check_instance(Path(args.instance_dir).expanduser().resolve()))
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight a ProgramBench paper-comparable Codex /goal host")
    parser.add_argument("--codex-user", default=os.environ.get("USER", "codex-runner"))
    parser.add_argument("--min-cpus", type=int, default=20)
    parser.add_argument("--min-memory-gib", type=int, default=60)
    parser.add_argument("--wrapper-command", default="/usr/local/bin/pb-target-exec")
    parser.add_argument("--instance-dir", default="")
    parser.add_argument("--check-egress-guard", action="store_true")
    parser.add_argument("--allow-direct-docker", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    checks = collect(args)
    if args.json:
        print(json.dumps([check.__dict__ for check in checks], indent=2, sort_keys=True))
    else:
        for check in checks:
            print(f"{'OK' if check.ok else 'FAIL'} {check.name}: {check.detail}")
    if any(not check.ok and check.strict for check in checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
