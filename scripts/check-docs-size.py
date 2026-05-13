#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


def mib(value: int) -> float:
    return value / (1024 * 1024)


def main() -> None:
    parser = argparse.ArgumentParser(description="Check GitHub Pages artifact size budgets")
    parser.add_argument("--docs-dir", default="docs")
    parser.add_argument("--max-file-mib", type=float, default=5)
    parser.add_argument("--max-total-mib", type=float, default=80)
    args = parser.parse_args()

    files = [path for path in Path(args.docs_dir).glob("**/*") if path.is_file()]
    total = sum(path.stat().st_size for path in files)
    failures = [
        f"{path}: {mib(path.stat().st_size):.2f} MiB exceeds {args.max_file_mib:.2f} MiB"
        for path in files
        if mib(path.stat().st_size) > args.max_file_mib
    ]
    if mib(total) > args.max_total_mib:
        failures.append(f"{args.docs_dir}: {mib(total):.2f} MiB exceeds {args.max_total_mib:.2f} MiB")
    for path in sorted(files, key=lambda item: item.stat().st_size, reverse=True)[:20]:
        print(f"{mib(path.stat().st_size):7.3f} MiB {path}")
    print(f"total={mib(total):.3f} MiB files={len(files)}")
    if failures:
        print("\n".join(f"FAIL {failure}" for failure in failures))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
