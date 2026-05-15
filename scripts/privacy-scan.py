#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def patterns() -> list[str]:
    home = str(Path.home())
    candidates = [
        home,
        str(Path.home().parent),
        str(Path.home() / "Documents"),
        "Documents/" + "ProgramBench",
    ]
    return [pattern for pattern in candidates if pattern and pattern != Path(pattern).anchor]


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan tracked public files for local machine paths")
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()

    results = [
        subprocess.run(
            ["rg", "-n", "-F", pattern, args.root, "--glob", "!local_state/**"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        for pattern in patterns()
    ]
    print("".join(result.stdout for result in results if result.returncode == 0), end="")
    if any(result.returncode == 0 for result in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
