#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class TokenUsage:
    calls: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0
    started_at: str = ""
    ended_at: str = ""
    session_logs: list[str] | None = None

    def estimated_cost_usd(self, rates: dict | None) -> float | None:
        input_rate = os.environ.get("CODEX_INPUT_USD_PER_MTOK")
        cached_rate = os.environ.get("CODEX_CACHED_INPUT_USD_PER_MTOK")
        output_rate = os.environ.get("CODEX_OUTPUT_USD_PER_MTOK")
        if input_rate is None and rates:
            input_rate = str(rates["input_usd_per_mtok"])
        if cached_rate is None and rates:
            cached_rate = str(rates["cached_input_usd_per_mtok"])
        if output_rate is None and rates:
            output_rate = str(rates["output_usd_per_mtok"])
        if input_rate is None or cached_rate is None or output_rate is None:
            return None
        uncached_input = max(0, self.input_tokens - self.cached_input_tokens)
        return (
            uncached_input * float(input_rate)
            + self.cached_input_tokens * float(cached_rate)
            + self.output_tokens * float(output_rate)
        ) / 1_000_000

    @property
    def wall_clock_seconds(self) -> int:
        if not self.started_at or not self.ended_at:
            return 0
        return int((parse_timestamp(self.ended_at) - parse_timestamp(self.started_at)).total_seconds())


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_programbench(programbench_repo: Path) -> tuple:
    sys.path.insert(0, str(programbench_repo / "src"))
    from programbench.eval.eval import EvaluationResult  # ty: ignore[unresolved-import]
    from programbench.eval.eval_batch import InstanceEvalSummary  # ty: ignore[unresolved-import]
    from programbench.utils.load_data import (  # ty: ignore[unresolved-import]
        get_active_branches,
        get_ignored_tests,
        load_all_instances,
    )

    return (
        EvaluationResult,
        InstanceEvalSummary,
        get_active_branches,
        get_ignored_tests,
        {instance["instance_id"]: instance for instance in load_all_instances(include_tests=True)},
    )


def score_eval(eval_json: Path, programbench: tuple) -> dict:
    EvaluationResult, InstanceEvalSummary, get_active_branches, get_ignored_tests, instances = programbench
    instance_id = eval_json.parent.name
    result = EvaluationResult.model_validate_json(eval_json.read_text())
    if instance_id in instances:
        result = result.for_branches(get_active_branches(instances[instance_id])).without_ignored(
            get_ignored_tests(instances[instance_id])
        )
    summary = InstanceEvalSummary.from_eval_result(instance_id, result)
    has_eval_errors = bool(
        summary.error_code or summary.test_branch_errors or summary.n_system_errors or summary.n_warnings
    )
    return {
        "instance_id": instance_id,
        "score": summary.score,
        "resolved": summary.score == 1.0 and summary.n_tests > 0 and not has_eval_errors,
        "almost_resolved": summary.score >= 0.95 and summary.n_tests > 0,
        "n_resolved_tests": summary.n_resolved,
        "n_tests": summary.n_tests,
        "error_code": summary.error_code or "",
        "test_branch_errors": json.dumps(summary.test_branch_errors, sort_keys=True),
        "n_system_errors": summary.n_system_errors,
        "n_warnings": summary.n_warnings,
    }


def session_meta(path: Path) -> dict | None:
    with path.open(errors="replace") as f:
        for line in f:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "session_meta":
                return event["payload"]
    return None


def token_usage(path: Path) -> TokenUsage:
    usage = TokenUsage(calls=0, session_logs=[str(path)])
    with path.open(errors="replace") as f:
        for line in f:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("timestamp"):
                usage.started_at = usage.started_at or event["timestamp"]
                usage.ended_at = event["timestamp"]
            payload = event.get("payload", {})
            if event.get("type") != "event_msg" or payload.get("type") != "token_count":
                continue
            info = payload.get("info")
            if not info:
                continue
            usage.calls += 1
            total = info["total_token_usage"]
            usage.input_tokens = total["input_tokens"]
            usage.cached_input_tokens = total["cached_input_tokens"]
            usage.output_tokens = total["output_tokens"]
            usage.reasoning_output_tokens = total["reasoning_output_tokens"]
            usage.total_tokens = total["total_tokens"]
    return usage


def add_usage(left: TokenUsage, right: TokenUsage) -> TokenUsage:
    return TokenUsage(
        calls=left.calls + right.calls,
        input_tokens=left.input_tokens + right.input_tokens,
        cached_input_tokens=left.cached_input_tokens + right.cached_input_tokens,
        output_tokens=left.output_tokens + right.output_tokens,
        reasoning_output_tokens=left.reasoning_output_tokens + right.reasoning_output_tokens,
        total_tokens=left.total_tokens + right.total_tokens,
        started_at=min(filter(None, [left.started_at, right.started_at]), default=""),
        ended_at=max(filter(None, [left.ended_at, right.ended_at]), default=""),
        session_logs=[*(left.session_logs or []), *(right.session_logs or [])],
    )


def find_codex_usage(instance_dir: Path, sessions_root: Path) -> TokenUsage:
    solution_dir = str(instance_dir / "solution")
    total = TokenUsage(session_logs=[])
    for path in sessions_root.glob("**/*.jsonl"):
        meta = session_meta(path)
        if meta and meta.get("cwd") == solution_dir:
            total = add_usage(total, token_usage(path))
    return total


def format_cost(cost: float | None) -> str:
    return "" if cost is None else f"{cost:.4f}"


def load_pricing(path: str) -> dict:
    pricing_path = Path(path).expanduser()
    if not pricing_path.is_file():
        return {}
    return json.loads(pricing_path.read_text()).get("models", {})


def summarize(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir).expanduser()
    programbench_repo = Path(args.programbench_repo).expanduser()
    programbench = load_programbench(programbench_repo)
    pricing = load_pricing(args.pricing_file)
    rows = []
    for eval_json in sorted(run_dir.glob("**/*.eval.json")):
        instance_dir = eval_json.parent
        eval_row = score_eval(eval_json, programbench)
        run = json.loads((instance_dir / "run.json").read_text()) if (instance_dir / "run.json").is_file() else {}
        usage = find_codex_usage(instance_dir, Path(args.codex_sessions).expanduser())
        model = run.get("model", "")
        rows.append(
            {
                **eval_row,
                "run_name": run.get("run_name", ""),
                "model": model,
                "reasoning_effort": run.get("reasoning_effort", ""),
                "inference_mode": run.get("inference_mode", ""),
                "paper_compliant": run.get("paper_compliant", ""),
                "host_system": run.get("host_system", ""),
                "host_machine": run.get("host_machine", ""),
                "docker_cpus": run.get("docker_cpus", ""),
                "docker_memory": run.get("docker_memory", ""),
                "created_at": run.get("created_at", ""),
                "calls": usage.calls,
                "wall_clock_seconds": usage.wall_clock_seconds,
                "session_started_at": usage.started_at,
                "session_ended_at": usage.ended_at,
                "input_tokens": usage.input_tokens,
                "cached_input_tokens": usage.cached_input_tokens,
                "output_tokens": usage.output_tokens,
                "reasoning_output_tokens": usage.reasoning_output_tokens,
                "total_tokens": usage.total_tokens,
                "estimated_cost_usd": format_cost(usage.estimated_cost_usd(pricing.get(model))),
                "pricing_source": pricing.get(model, {}).get("source_url", ""),
                "session_logs": ";".join(usage.session_logs or []),
            }
        )

    if args.output:
        with Path(args.output).expanduser().open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else [])
            writer.writeheader()
            writer.writerows(rows)

    total = len(rows)
    resolved = sum(row["resolved"] for row in rows)
    almost = sum(row["almost_resolved"] for row in rows)
    avg_pass = sum(row["score"] for row in rows) / total if total else 0
    print(f"instances,{total}")
    print(f"resolved_rate,{resolved / total if total else 0:.4f}")
    print(f"almost_resolved_rate,{almost / total if total else 0:.4f}")
    print(f"average_pass_rate,{avg_pass:.4f}")
    print(f"calls,{sum(row['calls'] for row in rows)}")
    print(f"wall_clock_hours,{sum(row['wall_clock_seconds'] for row in rows) / 3600:.2f}")
    costs = [float(row["estimated_cost_usd"]) for row in rows if row["estimated_cost_usd"]]
    print(f"estimated_cost_usd,{sum(costs):.4f}" if costs else "estimated_cost_usd,")


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize ProgramBench /goal results")
    parser.add_argument("run_dir")
    parser.add_argument("--programbench-repo", required=True)
    parser.add_argument("--codex-sessions", default=str(Path.home() / ".codex" / "sessions"))
    parser.add_argument("--pricing-file", default="local_state/openai_pricing.json")
    parser.add_argument("--output", default="")
    summarize(parser.parse_args())


if __name__ == "__main__":
    main()
