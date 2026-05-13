#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

LOCAL_ARTIFACTS = Path("local_state/run_artifacts")
DEFAULT_OUTPUT = Path("docs/evidence")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def scrub_metrics(metrics: dict) -> dict:
    return {key: value for key, value in metrics.items() if key != "session_logs"}


def status_counts(eval_json: dict) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in eval_json.get("test_results", []):
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    return counts


def failed_tests(eval_json: dict) -> list[dict]:
    return [
        {
            "name": result["name"],
            "branch": result.get("branch", ""),
            "status": result["status"],
            "message": result.get("extra", {}).get("message", ""),
        }
        for result in eval_json.get("test_results", [])
        if result["status"] != "passed"
    ]


def eval_summary(eval_json: dict) -> dict:
    results = eval_json.get("test_results", [])
    return {
        "test_records": len(results),
        "status_counts": status_counts(eval_json),
        "failed_tests": failed_tests(eval_json),
        "error_code": eval_json.get("error_code"),
        "error_details": eval_json.get("error_details"),
        "test_branches": eval_json.get("test_branches", []),
        "test_branch_errors": eval_json.get("test_branch_errors", {}),
        "executable_hash": eval_json.get("executable_hash"),
        "warnings": eval_json.get("warnings", []),
        "evaluator_log_steps": [
            {
                "step": entry.get("step", ""),
                "branch": entry.get("branch", ""),
                "returncode": entry.get("returncode"),
                "wall_time": entry.get("wall_time"),
                "exception_info": entry.get("exception_info", ""),
            }
            for entry in eval_json.get("log", [])
        ],
    }


def public_manifest(manifest: dict, eval_summary_path: str) -> dict:
    return {
        "collected_at": manifest["collected_at"],
        "instance_id": manifest["run"]["instance_id"],
        "run_name": manifest["run"]["run_name"],
        "model": manifest["run"]["model"],
        "reasoning_effort": manifest["run"]["reasoning_effort"],
        "inference_mode": manifest["run"]["inference_mode"],
        "paper_compliant": manifest["run"]["paper_compliant"],
        "host_system": manifest["run"]["host_system"],
        "host_machine": manifest["run"]["host_machine"],
        "docker_cpus": manifest["run"]["docker_cpus"],
        "docker_memory": manifest["run"]["docker_memory"],
        "metrics": scrub_metrics(manifest.get("metrics", {})),
        "eval": {
            "test_records": manifest["eval"]["test_records"],
            "failed_tests": manifest["eval"]["failed_tests"],
            "error_code": manifest["eval"]["error_code"],
            "test_branch_errors": manifest["eval"]["test_branch_errors"],
            "warnings": manifest["eval"]["warnings"],
            "summary_path": eval_summary_path,
        },
        "package": {
            "contents": manifest["package"]["contents"],
            "submission_available_local_only": bool(manifest["copied_files"].get("submission")),
        },
        "agent_trace": {
            "codex_logs_available_local_only": bool(
                [path for path in manifest["copied_files"].get("codex_logs", []) if path]
            ),
            "raw_logs_published": False,
        },
    }


def export_one(manifest_path: Path, output_dir: Path) -> None:
    manifest = read_json(manifest_path)
    instance_id = manifest["run"]["instance_id"]
    run_name = manifest["run"]["run_name"]
    target_dir = output_dir / run_name / instance_id
    target_dir.mkdir(parents=True, exist_ok=True)

    eval_json_path = manifest_path.parent / f"{instance_id}.eval.json"
    summary_name = "eval-summary.json"
    (target_dir / summary_name).write_text(
        json.dumps(eval_summary(read_json(eval_json_path)), indent=2, sort_keys=True) + "\n"
    )
    (target_dir / "manifest.json").write_text(
        json.dumps(public_manifest(manifest, summary_name), indent=2, sort_keys=True) + "\n"
    )
    print(target_dir)


def export(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir)
    for manifest_path in sorted(Path(args.artifacts_dir).glob("*/*/manifest.json")):
        export_one(manifest_path, output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export sanitized public evidence from local run artifacts")
    parser.add_argument("--artifacts-dir", default=str(LOCAL_ARTIFACTS))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT))
    export(parser.parse_args())


if __name__ == "__main__":
    main()
