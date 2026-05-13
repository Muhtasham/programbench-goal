#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.request import Request, urlopen

PROGRAMBENCH_EXTENDED = "https://programbench.com/extended/"
TARGET_MODELS = {"GPT 5.5 (xhigh)", "GPT 5.5 (high)"}
ROW_RE = re.compile(r"<tr class=\"clickable-row\".*?</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


def fetch(url: str) -> str:
    with urlopen(Request(url, headers={"User-Agent": "programbench-goal-runner/0.1"}), timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def clean_html(value: str) -> str:
    return " ".join(unescape(TAG_RE.sub(" ", value)).split())


def parse_percent(value: str) -> float:
    return float(value.rstrip("%")) / 100


def parse_money(value: str) -> float:
    return float(value.lstrip("$"))


def parse_rows(html: str) -> list[dict]:
    rows = []
    for row in ROW_RE.findall(html):
        cells = [clean_html(cell) for cell in CELL_RE.findall(row)]
        if len(cells) < 8 or cells[2] not in TARGET_MODELS:
            continue
        rows.append(
            {
                "model": cells[2],
                "agent": cells[3],
                "resolved_rate": parse_percent(cells[4]),
                "almost_resolved_rate": parse_percent(cells[5]),
                "average_cost_usd": parse_money(cells[6]),
                "average_calls": int(float(cells[7])),
                "source": PROGRAMBENCH_EXTENDED,
            }
        )
    return rows


def refresh(args: argparse.Namespace) -> None:
    rows = parse_rows(fetch(args.url))
    missing = TARGET_MODELS - {row["model"] for row in rows}
    if missing:
        raise ValueError(f"missing baseline rows: {sorted(missing)}")
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "source": args.url,
                "baselines": rows,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(output)
    for row in rows:
        print(
            ",".join(
                [
                    row["model"],
                    row["agent"],
                    str(row["resolved_rate"]),
                    str(row["almost_resolved_rate"]),
                    str(row["average_cost_usd"]),
                    str(row["average_calls"]),
                ]
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh ProgramBench public baseline rows")
    parser.add_argument("--url", default=PROGRAMBENCH_EXTENDED)
    parser.add_argument("--output", default="docs/data/programbench-baselines.json")
    refresh(parser.parse_args())


if __name__ == "__main__":
    main()
