#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def target_ids(path: Path) -> list[str]:
    return [line.split("#", 1)[0].strip() for line in path.read_text().splitlines() if line.split("#", 1)[0].strip()]


def load_instance_ids(programbench_repo: Path) -> list[str]:
    tasks_dir = programbench_repo / "src" / "programbench" / "data" / "tasks"
    return sorted(path.name for path in tasks_dir.iterdir() if path.is_dir() and (path / "task.yaml").is_file())


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a ProgramBench target set against task metadata")
    parser.add_argument("target_file")
    parser.add_argument("--programbench-repo", required=True)
    parser.add_argument("--expected-count", type=int, default=200)
    parser.add_argument("--include-fixtures", action="store_true")
    parser.add_argument("--allow-subset", action="store_true")
    args = parser.parse_args()

    expected = [
        instance_id
        for instance_id in load_instance_ids(Path(args.programbench_repo).expanduser().resolve())
        if args.include_fixtures or not instance_id.startswith("testorg__")
    ]
    actual = target_ids(Path(args.target_file).expanduser())
    duplicates = sorted({instance_id for instance_id in actual if actual.count(instance_id) > 1})
    missing = [] if args.allow_subset else sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    if len(actual) != args.expected_count or duplicates or missing or extra:
        raise SystemExit(
            "\n".join(
                [
                    f"target set invalid: expected_count={args.expected_count} actual_count={len(actual)}",
                    f"duplicates={duplicates[:20]}",
                    f"missing={missing[:20]}",
                    f"extra={extra[:20]}",
                ]
            )
        )
    print(f"{args.target_file} valid instances={len(actual)}")


if __name__ == "__main__":
    main()
