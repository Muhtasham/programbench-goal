#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import tarfile
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_TOOLS = (
    "brew",
    "dtruss",
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
    "uv",
    "xxd",
)
SOURCE_LOOKUP_PATTERNS = (
    r"\bcargo\s+install\b",
    r"\bcargo\s+search\b",
    r"\bcargo\s+add\b",
    r"\bgo\s+get\b",
    r"\bgo\s+install\s+[\w./-]+@",
    r"\bpip3?\s+install\b",
    r"\bnpm\s+install\b",
    r"\byarn\s+add\b",
    r"\bpnpm\s+add\b",
    r"\bapt(-get)?\s+source\b",
    r"\bapt(-get)?\s+install\b",
    r"\bbrew\s+install\b",
    r"\bgh\s+repo\s+clone\b",
    r"\bgit\s+clone\b",
    r"\bgit\s+remote\b",
    r"\bgit\s+fetch\b",
    r"\bgit\s+pull\b",
    r"\bgit\s+checkout\b",
    r"\.cargo/registry/src",
    r"/go/pkg/mod",
    r"\$\(go env GOPATH\)/pkg/mod",
)
LOCALHOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0"}
HOST_PATH_MARKERS = (
    "/" + "Users" + "/",
    "/Documents/" + "ProgramBench",
)
BINARY_ANALYSIS_TOOLS = (
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
)
PARENT_INSPECTION = re.compile(r"(^|[;&|]\s*)(cat|find|grep|head|ls|rg|sed|tail|wc)\s+[^;&|]*\.\.")
PARENT_DIRECTORY_CHANGE = re.compile(r"(^|[;&|]\s*)(cd|pushd)\s+\.\.(?:[/\s;&|]|$)")
HARNESS_PARENT_PATH = re.compile(
    r"\.\./(?:package-submission|start-target|check-compliance|eval-submission|run\.json|GOAL_PROMPT|GOAL_OBJECTIVE)"
)
WRAPPER_PATTERNS = (
    r"/workspace/executable",
    r"\bdocker\s+exec\b",
    r"\bprogrambench\b",
    r"\bexec\s+[^;\n]*\s+\"\$@\"",
    r"\bsubprocess\.[^(]+\(.*executable",
    r"\bCommand::new\([^)]*executable",
)
PAPER_CACHE_ENV = {
    "CARGO_HOME",
    "CARGO_NET_OFFLINE",
    "GOMODCACHE",
    "GOPATH",
    "GOPROXY",
    "GOSUMDB",
    "NPM_CONFIG_CACHE",
    "NPM_CONFIG_OFFLINE",
    "PIP_CACHE_DIR",
    "PIP_NO_INDEX",
}


@dataclass
class Finding:
    source: str
    message: str
    command: str = ""
    strict_only: bool = False


def session_meta(path: Path) -> dict | None:
    return next(
        (
            event["payload"]
            for event in (json.loads(line) for line in path.read_text(errors="replace").splitlines())
            if event.get("type") == "session_meta"
        ),
        None,
    )


def exec_calls(path: Path) -> list[tuple[int, dict, str]]:
    events = [
        (n, event, event.get("payload", {}))
        for n, event in enumerate(
            (json.loads(line) for line in path.read_text(errors="replace").splitlines()),
            start=1,
        )
    ]
    calls = [
        (n, payload["call_id"], json.loads(payload["arguments"]))
        for n, event, payload in events
        if event.get("type") == "response_item"
        and payload.get("type") == "function_call"
        and payload.get("name") == "exec_command"
    ]
    outputs = {
        payload["call_id"]: payload.get("output", "")
        for _, event, payload in events
        if event.get("type") == "response_item" and payload.get("type") == "function_call_output"
    }
    return [(line, call, outputs.get(call_id, "")) for line, call_id, call in calls]


def was_blocked(output: str) -> bool:
    return "blocked " in output or "Failed to create unified exec process" in output


def uses_tool(command: str, tool: str) -> bool:
    path = r"(?:/(?:bin|usr/bin|usr/local/bin|opt/homebrew/bin)/)?"
    return bool(re.search(rf"(^|[\s;&|()]){path}{re.escape(tool)}([\s;&|()]|$)", command))


def uses_binary_analysis_on_target(command: str, tool: str) -> bool:
    tool_path = rf"(?:/(?:bin|usr/bin|usr/local/bin|opt/homebrew/bin)/)?{re.escape(tool)}"
    return any(
        re.search(rf"(^|[\s;&|()]){tool_path}([\s;&|()]|$)[^;&|]*?/workspace/executable", segment)
        for segment in re.split(r"(?:;|\n|&&|\|\|)", command)
    )


def uses_allowed_docker(command: str, container_name: str) -> bool:
    return bool(re.search(rf"\bdocker\s+exec\s+(?:-i\s+)?-u\s+agent\s+{re.escape(container_name)}\b", command))


def uses_allowed_local_tools_docker(command: str, container_name: str) -> bool:
    escaped = re.escape(container_name)
    return bool(
        re.search(rf"\bdocker\s+exec\s+(?:-i\s+)?{escaped}\b", command)
        or re.search(rf"\bdocker\s+cp\s+{escaped}:/", command)
        or re.search(rf"\bdocker\s+inspect\s+{escaped}\b", command)
    )


def is_inside(path: str, root: Path) -> bool:
    candidate = Path(path).expanduser()
    return candidate == root or root in candidate.parents


def find_session_logs(instance_dir: Path, sessions_root: Path) -> list[Path]:
    solution_dir = str(instance_dir / "solution")
    return [
        path
        for path in sorted(sessions_root.glob("**/*.jsonl"))
        if (session_meta(path) or {}).get("cwd") == solution_dir
    ]


def text_files(root: Path) -> list[Path]:
    return [path for path in sorted(root.rglob("*")) if is_small_text_file(path)]


def is_small_text_file(path: Path) -> bool:
    if not (path.is_file() and path.name != "AGENT_RULES.md" and path.stat().st_size < 2_000_000):
        return False
    try:
        path.read_text(errors="strict")
    except UnicodeDecodeError:
        return False
    return True


def audit_solution_files(solution_dir: Path) -> list[Finding]:
    return [
        Finding(str(path), f"solution file contains wrapper/evaluator pattern: {pattern}")
        for path in text_files(solution_dir)
        for pattern in WRAPPER_PATTERNS
        if re.search(pattern, path.read_text(errors="replace"))
    ]


def audit_submission_archive(instance_dir: Path) -> list[Finding]:
    archive = instance_dir / "submission.tar.gz"
    if not archive.exists():
        return []
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    return [
        *(
            []
            if any(name.strip("./") == "compile.sh" for name in names)
            else [Finding(str(archive), "submission archive does not include compile.sh")]
        ),
        *(
            [Finding(str(archive), "submission archive includes harness-only AGENT_RULES.md")]
            if any(name.strip("./") == "AGENT_RULES.md" for name in names)
            else []
        ),
        *[
            Finding(str(archive), f"submission archive contains unsafe path: {name}")
            for name in names
            if name.startswith("/") or ".." in Path(name).parts
        ],
    ]


def audit_paper_settings(run: dict, instance_dir: Path) -> list[Finding]:
    findings = []
    if run.get("inference_mode", "paper") != "paper" or not run.get("paper_compliant", True):
        findings.append(
            Finding(
                str(instance_dir / "run.json"),
                "run is not in ProgramBench paper-compliant inference mode",
                strict_only=True,
            )
        )
    if run.get("host_system") != "Linux":
        findings.append(
            Finding(str(instance_dir / "run.json"), "paper-comparable run should use Linux host", strict_only=True)
        )
    if run.get("host_machine") not in {"x86_64", "AMD64"}:
        findings.append(
            Finding(str(instance_dir / "run.json"), "paper-comparable run should use amd64 host", strict_only=True)
        )
    if run.get("docker_cpus") != 20:
        findings.append(Finding(str(instance_dir / "run.json"), "paper uses 20 CPUs per run", strict_only=True))
    if run.get("docker_memory") != "60g":
        findings.append(Finding(str(instance_dir / "run.json"), "paper uses 60GB RAM per run", strict_only=True))
    if not PAPER_CACHE_ENV.issubset(set(run.get("tool_cache_env", []))):
        findings.append(
            Finding(
                str(instance_dir / "run.json"),
                "paper-mode run should isolate package/tool caches",
                strict_only=True,
            )
        )
    return findings


def audit_command(
    line_source: str,
    call: dict,
    output: str,
    solution_dir: Path,
    container_name: str,
    allow_local_tools: bool,
) -> list[Finding]:
    findings = []
    if was_blocked(output):
        return findings
    command = call["cmd"]
    workdir = call.get("workdir", "")
    if workdir and not is_inside(workdir, solution_dir):
        findings.append(Finding(line_source, f"exec workdir escapes solution dir: {workdir}", command))
    if any(marker in command for marker in HOST_PATH_MARKERS):
        findings.append(Finding(line_source, "command contains private host or evaluator path", command))
    if PARENT_INSPECTION.search(command):
        findings.append(Finding(line_source, "command inspects parent directories from solution workspace", command))
    elif PARENT_DIRECTORY_CHANGE.search(command) or HARNESS_PARENT_PATH.search(command):
        findings.append(
            Finding(line_source, "command uses parent-directory traversal from solution workspace", command)
        )
    if uses_tool(command, "docker") and not (
        uses_allowed_local_tools_docker(command, container_name)
        if allow_local_tools
        else uses_allowed_docker(command, container_name)
    ):
        findings.append(Finding(line_source, "docker command does not use the allowed target exec form", command))
    if "/workspace/executable" in command and not allow_local_tools:
        findings.extend(
            Finding(line_source, f"binary analysis tool used on target executable: {tool}", command)
            for tool in BINARY_ANALYSIS_TOOLS
            if uses_binary_analysis_on_target(command, tool)
        )
    findings.extend(
        Finding(line_source, f"source/package lookup pattern: {pattern}", command)
        for pattern in SOURCE_LOOKUP_PATTERNS
        if re.search(pattern, command)
    )
    findings.extend(
        Finding(line_source, f"external URL fetch: {match.group(0)}", command)
        for match in re.finditer(r"\b(?:curl|wget)\b[^;&|]*\bhttps?://([^/\s'\"]+)", command)
        if match.group(1).rsplit(":", 1)[0] not in LOCALHOSTS
    )
    findings.extend(
        Finding(line_source, f"forbidden cleanroom host/tool command: {tool}", command)
        for tool in FORBIDDEN_TOOLS
        if tool not in BINARY_ANALYSIS_TOOLS and uses_tool(command, tool) and tool != "docker"
    )
    return findings


def audit(args: argparse.Namespace) -> None:
    instance_dir = Path(args.instance_dir).expanduser().resolve()
    run = json.loads((instance_dir / "run.json").read_text())
    solution_dir = instance_dir / "solution"
    findings = []

    if not (solution_dir / "compile.sh").is_file():
        findings.append(Finding(str(solution_dir / "compile.sh"), "missing ProgramBench compile.sh"))
    if (instance_dir / "submission.tar.gz").is_file() and not (solution_dir / "compile.sh").is_file():
        findings.append(
            Finding(str(instance_dir / "submission.tar.gz"), "submission exists but cannot compile without compile.sh")
        )
    findings.extend(audit_solution_files(solution_dir))
    findings.extend(audit_submission_archive(instance_dir))
    findings.extend(audit_paper_settings(run, instance_dir))

    logs = find_session_logs(instance_dir, Path(args.codex_sessions).expanduser())
    if not logs:
        findings.append(Finding(str(instance_dir), "no Codex JSONL session logs found for solution cwd"))
    blocked_attempts = 0
    if run.get("inference_mode") != "open-internet":
        calls = [(log, line, call, output) for log in logs for line, call, output in exec_calls(log)]
        blocked_attempts = sum(was_blocked(output) for _, _, _, output in calls)
        findings.extend(
            finding
            for log, line, call, output in calls
            for finding in audit_command(
                f"{log}:{line}",
                call,
                output,
                solution_dir,
                run["container_name"],
                run.get("inference_mode") == "no-internet-local-tools",
            )
        )

    findings = [finding for finding in findings if args.strict_paper or not finding.strict_only]
    if findings:
        print("\n".join(failure_text(finding) for finding in findings))
        raise SystemExit(1)
    print(f"OK audit passed for {instance_dir}")
    print(f"session_logs={';'.join(str(path) for path in logs)}")
    print(f"blocked_attempts={blocked_attempts}")


def failure_text(finding: Finding) -> str:
    return (
        f"FAIL {finding.source}: {finding.message}\n  cmd: {finding.command}"
        if finding.command
        else f"FAIL {finding.source}: {finding.message}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit a Codex /goal ProgramBench run for cleanroom gaps")
    parser.add_argument("instance_dir")
    parser.add_argument("--codex-sessions", default=str(Path.home() / ".codex" / "sessions"))
    parser.add_argument(
        "--strict-paper",
        action="store_true",
        help="fail on paper-comparability gaps such as host/resources",
    )
    audit(parser.parse_args())


if __name__ == "__main__":
    main()
