#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TokenUsage:
    calls: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0
    session_logs: list[str] | None = None

    @property
    def estimated_cost_usd(self) -> float | None:
        input_rate = os.environ.get("CODEX_INPUT_USD_PER_MTOK")
        cached_rate = os.environ.get("CODEX_CACHED_INPUT_USD_PER_MTOK")
        output_rate = os.environ.get("CODEX_OUTPUT_USD_PER_MTOK")
        if input_rate is None or cached_rate is None or output_rate is None:
            return None
        uncached_input = max(0, self.input_tokens - self.cached_input_tokens)
        return (
            uncached_input * float(input_rate)
            + self.cached_input_tokens * float(cached_rate)
            + self.output_tokens * float(output_rate)
        ) / 1_000_000


def load_programbench(programbench_repo: Path):
    sys.path.insert(0, str(programbench_repo / "src"))
    from programbench.eval.eval import EvaluationResult
    from programbench.utils.load_data import get_active_branches, get_ignored_tests, load_all_instances

    return EvaluationResult, get_active_branches, get_ignored_tests, {
        instance["instance_id"]: instance for instance in load_all_instances(include_tests=True)
    }


def score_eval(eval_json: Path, programbench_repo: Path) -> dict:
    EvaluationResult, get_active_branches, get_ignored_tests, instances = load_programbench(programbench_repo)
    instance_id = eval_json.parent.name
    result = EvaluationResult.model_validate_json(eval_json.read_text())
    if instance_id in instances:
        result = result.for_branches(get_active_branches(instances[instance_id])).without_ignored(
            get_ignored_tests(instances[instance_id])
        )
    return {
        "instance_id": instance_id,
        "score": result.score,
        "resolved": result.score == 1.0 and len(result) > 0,
        "almost_resolved": result.score > 0.95 and len(result) > 0,
        "n_resolved_tests": result.n_resolved,
        "n_tests": len(result),
        "error_code": result.error_code or "",
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


def summarize(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir).expanduser()
    programbench_repo = Path(args.programbench_repo).expanduser()
    rows = []
    for eval_json in sorted(run_dir.glob("*/*.eval.json")):
        instance_dir = eval_json.parent
        eval_row = score_eval(eval_json, programbench_repo)
        usage = find_codex_usage(instance_dir, Path(args.codex_sessions).expanduser())
        rows.append({
            **eval_row,
            "calls": usage.calls,
            "input_tokens": usage.input_tokens,
            "cached_input_tokens": usage.cached_input_tokens,
            "output_tokens": usage.output_tokens,
            "reasoning_output_tokens": usage.reasoning_output_tokens,
            "total_tokens": usage.total_tokens,
            "estimated_cost_usd": format_cost(usage.estimated_cost_usd),
            "session_logs": ";".join(usage.session_logs or []),
        })

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
    costs = [float(row["estimated_cost_usd"]) for row in rows if row["estimated_cost_usd"]]
    print(f"estimated_cost_usd,{sum(costs):.4f}" if costs else "estimated_cost_usd,")


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize ProgramBench /goal results")
    parser.add_argument("run_dir")
    parser.add_argument("--programbench-repo", required=True)
    parser.add_argument("--codex-sessions", default=str(Path.home() / ".codex" / "sessions"))
    parser.add_argument("--output", default="")
    summarize(parser.parse_args())


if __name__ == "__main__":
    main()
