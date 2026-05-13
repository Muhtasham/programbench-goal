#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path

HOME = str(Path.home())
HOME_TOKEN = "$HOME"
REDACTIONS = [
    (str(Path.home() / "Documents" / "ProgramBench"), "$PROGRAMBENCH_REPO"),
    (str(Path.home() / "pb-goal-runs"), "$RUNS_ROOT"),
    (str(Path.home() / ".codex" / "sessions"), "$CODEX_SESSIONS"),
    (HOME, HOME_TOKEN),
    (f"{HOME_TOKEN}/Documents" + "/ProgramBench", "$PROGRAMBENCH_REPO"),
    (f"{HOME_TOKEN}/pb-goal-runs", "$RUNS_ROOT"),
    (f"{HOME_TOKEN}/.codex/sessions", "$CODEX_SESSIONS"),
]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() else {}


def package_listing(path: Path) -> list[str]:
    if not path.is_file():
        return []
    with tarfile.open(path) as tar:
        return sorted(tar.getnames())


def failed_tests(eval_json: dict) -> list[str]:
    return [result["name"] for result in eval_json.get("test_results", []) if result.get("status") != "passed"]


def results_row(results_csv: Path, instance_id: str) -> dict:
    if not results_csv.is_file():
        return {}
    with results_csv.open(newline="") as f:
        for row in csv.DictReader(f):
            if row["instance_id"] == instance_id:
                return row
    return {}


def copy_if_exists(source: Path, target: Path) -> str:
    if not source.is_file():
        return ""
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return str(target)


def redact(value):
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        for source, target in REDACTIONS:
            value = value.replace(source, target)
        return value
    return value


def copy_text_if_exists(source: Path, target: Path) -> str:
    if not source.is_file():
        return ""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(redact(source.read_text(errors="replace")))
    return str(target)


def collect(args: argparse.Namespace) -> None:
    instance_dir = Path(args.instance_dir).expanduser().resolve()
    run = read_json(instance_dir / "run.json")
    instance_id = run.get("instance_id", instance_dir.name)
    run_name = run.get("run_name", instance_dir.parent.name)
    output_dir = Path(args.output_dir).expanduser() / run_name / instance_id
    output_dir.mkdir(parents=True, exist_ok=True)

    eval_path = instance_dir / f"{instance_id}.eval.json"
    eval_json = read_json(eval_path)
    row = results_row(
        Path(args.results_csv).expanduser() if args.results_csv else instance_dir.parent / "results.csv", instance_id
    )
    copied_logs = []
    for session_log in filter(None, row.get("session_logs", "").split(";")):
        copied_logs.append(copy_text_if_exists(Path(session_log), output_dir / "codex_logs" / Path(session_log).name))

    manifest = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "instance_dir": str(instance_dir),
        "run": redact(run),
        "eval": {
            "path": str(eval_path),
            "test_records": len(eval_json.get("test_results", [])),
            "failed_tests": failed_tests(eval_json),
            "error_code": eval_json.get("error_code"),
            "test_branch_errors": eval_json.get("test_branch_errors"),
            "warnings": eval_json.get("warnings") or [],
        },
        "metrics": redact(row),
        "package": {
            "path": str(instance_dir / "submission.tar.gz"),
            "contents": package_listing(instance_dir / "submission.tar.gz"),
        },
        "copied_files": {
            "run_json": copy_text_if_exists(instance_dir / "run.json", output_dir / "run.json"),
            "eval_json": copy_text_if_exists(eval_path, output_dir / eval_path.name),
            "results_csv": copy_text_if_exists(instance_dir.parent / "results.csv", output_dir / "results.csv"),
            "usage_audit": copy_text_if_exists(
                (
                    Path(args.results_csv).expanduser() if args.results_csv else instance_dir.parent / "results.csv"
                ).with_name("usage-audit.json"),
                output_dir / "usage-audit.json",
            ),
            "submission": copy_if_exists(instance_dir / "submission.tar.gz", output_dir / "submission.tar.gz"),
            "codex_logs": copied_logs,
        },
    }
    manifest = redact(manifest)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(output_dir)
    print(f"failed_tests,{len(manifest['eval']['failed_tests'])}")
    print(f"codex_logs,{len([path for path in copied_logs if path])}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect local, uncommitted ProgramBench /goal run artifacts")
    parser.add_argument("instance_dir")
    parser.add_argument("--output-dir", default="local_state/run_artifacts")
    parser.add_argument("--results-csv", default="")
    collect(parser.parse_args())


if __name__ == "__main__":
    main()
