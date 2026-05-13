#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.request import Request, urlopen

PROGRAMBENCH_TASK = "https://programbench.com/task/{instance_id}/"
ROW_RE = re.compile(r"<tr class=\"clickable-row\".*?</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
STAT_RE = re.compile(r'<div class="stat-num">([^<]+)</div>\s*<div class="stat-label">([^<]+)</div>')


def fetch(url: str) -> str:
    with urlopen(Request(url, headers={"User-Agent": "programbench-goal/0.1"}), timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def clean_html(value: str) -> str:
    return " ".join(unescape(TAG_RE.sub(" ", value)).split())


def parse_percent(value: str) -> float | None:
    return None if value == "n/a" else float(value.rstrip("%")) / 100


def parse_money(value: str) -> float:
    return float(value.lstrip("$"))


def target_ids(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]


def parse_task(instance_id: str, html: str) -> dict:
    stats = {label: value for value, label in STAT_RE.findall(html)}
    rows = []
    for row in ROW_RE.findall(html):
        cells = [clean_html(cell) for cell in CELL_RE.findall(row)]
        if len(cells) < 6:
            continue
        model = re.search(r'<span class="model-name">([^<]+)</span>', row)
        provider = re.search(r'<span class="model-provider">([^<]+)</span>', row)
        rows.append(
            {
                "model": clean_html(model.group(1)) if model else cells[2],
                "provider": clean_html(provider.group(1)) if provider else "",
                "score": parse_percent(cells[3]),
                "cost_usd": parse_money(cells[4]),
                "calls": int(float(cells[5].replace(",", ""))),
                "source": PROGRAMBENCH_TASK.format(instance_id=instance_id),
            }
        )
    return {
        "instance_id": instance_id,
        "source": PROGRAMBENCH_TASK.format(instance_id=instance_id),
        "generated_tests": int(stats["Generated Behavioral Tests"].replace(",", "")),
        "best_score": parse_percent(stats["Best Score"]),
        "results": rows,
    }


def refresh(args: argparse.Namespace) -> None:
    output = Path(args.output).expanduser()
    existing = json.loads(output.read_text()) if args.merge_existing and output.exists() else {}
    tasks = existing.get("tasks", {})
    tasks.update(
        {
            instance_id: parse_task(instance_id, fetch(PROGRAMBENCH_TASK.format(instance_id=instance_id)))
            for instance_id in target_ids(Path(args.target_set).expanduser())
        }
    )
    data = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "https://programbench.com/task/<instance_id>/",
        "tasks": tasks,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(output)
    print(f"tasks,{len(data['tasks'])}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh ProgramBench per-task public baseline rows")
    parser.add_argument("--target-set", default="target_sets/all_tasks.txt")
    parser.add_argument("--output", default="docs/data/programbench-task-baselines.json")
    parser.add_argument("--merge-existing", action="store_true")
    refresh(parser.parse_args())


if __name__ == "__main__":
    main()
