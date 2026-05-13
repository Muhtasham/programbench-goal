#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
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
    r"\bGOMODCACHE\b",
)
LOCALHOSTS = {"127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0"}
HOST_PATH_MARKERS = ("/" "Users/", "/" "Documents/" "ProgramBench")
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


@dataclass
class Finding:
    source: str
    message: str
    command: str = ""


def session_meta(path: Path) -> dict | None:
    for line in path.read_text(errors="replace").splitlines():
        event = json.loads(line)
        if event.get("type") == "session_meta":
            return event["payload"]
    return None


def exec_calls(path: Path) -> list[tuple[int, dict]]:
    calls = []
    for n, line in enumerate(path.read_text(errors="replace").splitlines(), start=1):
        event = json.loads(line)
        payload = event.get("payload", {})
        if event.get("type") == "response_item" and payload.get("type") == "function_call":
            if payload.get("name") == "exec_command":
                calls.append((n, json.loads(payload["arguments"])))
    return calls


def uses_tool(command: str, tool: str) -> bool:
    path = r"(?:/(?:bin|usr/bin|usr/local/bin|opt/homebrew/bin)/)?"
    return bool(re.search(rf"(^|[\s;&|()]){path}{re.escape(tool)}([\s;&|()]|$)", command))


def uses_allowed_docker(command: str, container_name: str) -> bool:
    return bool(re.search(rf"\bdocker\s+exec\s+(?:-i\s+)?-u\s+agent\s+{re.escape(container_name)}\b", command))


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


def audit_command(
    line_source: str,
    command: str,
    workdir: str,
    solution_dir: Path,
    container_name: str,
) -> list[Finding]:
    findings = []
    if workdir and not is_inside(workdir, solution_dir):
        findings.append(Finding(line_source, f"exec workdir escapes solution dir: {workdir}", command))
    if any(marker in command for marker in HOST_PATH_MARKERS):
        findings.append(Finding(line_source, "command contains private host or evaluator path", command))
    if PARENT_INSPECTION.search(command):
        findings.append(Finding(line_source, "command inspects parent directories from solution workspace", command))
    if uses_tool(command, "docker") and not uses_allowed_docker(command, container_name):
        findings.append(Finding(line_source, "docker command does not use the allowed target exec form", command))
    if "/workspace/executable" in command:
        for tool in BINARY_ANALYSIS_TOOLS:
            if uses_tool(command, tool):
                findings.append(Finding(line_source, f"binary analysis tool used on target executable: {tool}", command))
    for pattern in SOURCE_LOOKUP_PATTERNS:
        if re.search(pattern, command):
            findings.append(Finding(line_source, f"source/package lookup pattern: {pattern}", command))
    for match in re.finditer(r"\b(?:curl|wget)\b[^;&|]*\bhttps?://([^/\s'\"]+)", command):
        host = match.group(1).rsplit(":", 1)[0]
        if host not in LOCALHOSTS:
            findings.append(Finding(line_source, f"external URL fetch: {match.group(0)}", command))
    for tool in FORBIDDEN_TOOLS:
        if uses_tool(command, tool) and tool != "docker":
            findings.append(Finding(line_source, f"forbidden cleanroom host/tool command: {tool}", command))
    return findings


def audit(args: argparse.Namespace) -> None:
    instance_dir = Path(args.instance_dir).expanduser().resolve()
    run = json.loads((instance_dir / "run.json").read_text())
    solution_dir = instance_dir / "solution"
    findings = []

    if not (solution_dir / "compile.sh").is_file():
        findings.append(Finding(str(solution_dir / "compile.sh"), "missing ProgramBench compile.sh"))
    if (instance_dir / "submission.tar.gz").is_file() and not (solution_dir / "compile.sh").is_file():
        findings.append(Finding(str(instance_dir / "submission.tar.gz"), "submission exists but cannot compile without compile.sh"))

    logs = find_session_logs(instance_dir, Path(args.codex_sessions).expanduser())
    if not logs:
        findings.append(Finding(str(instance_dir), "no Codex JSONL session logs found for solution cwd"))
    for log in logs:
        for line, call in exec_calls(log):
            findings.extend(
                audit_command(
                    f"{log}:{line}",
                    call["cmd"],
                    call.get("workdir", ""),
                    solution_dir,
                    run["container_name"],
                )
            )

    if findings:
        for finding in findings:
            print(f"FAIL {finding.source}: {finding.message}")
            if finding.command:
                print(f"  cmd: {finding.command}")
        raise SystemExit(1)
    print(f"OK audit passed for {instance_dir}")
    print(f"session_logs={';'.join(str(path) for path in logs)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit a Codex /goal ProgramBench run for cleanroom gaps")
    parser.add_argument("instance_dir")
    parser.add_argument("--codex-sessions", default=str(Path.home() / ".codex" / "sessions"))
    audit(parser.parse_args())


if __name__ == "__main__":
    main()
