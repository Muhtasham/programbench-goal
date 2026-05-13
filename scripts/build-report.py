#!/usr/bin/env python3
# ruff: noqa: E501
from __future__ import annotations

import argparse
import csv
import html
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ResultRow:
    instance_id: str
    run_name: str
    model: str
    reasoning_effort: str
    inference_mode: str
    paper_compliant: bool
    score: float
    resolved: bool
    almost_resolved: bool
    n_resolved_tests: int
    n_tests: int
    calls: int
    wall_clock_seconds: int
    estimated_cost_usd: float
    host_system: str
    host_machine: str
    docker_cpus: str
    docker_memory: str
    pricing_source: str


BASELINES = [
    {
        "model": "GPT 5.5 (xhigh)",
        "agent": "mini-SWE-agent",
        "resolved_rate": 0.005,
        "almost_resolved_rate": 0.135,
        "average_cost_usd": 8.85,
        "average_calls": 82,
        "source": "https://programbench.com/extended/",
    },
    {
        "model": "GPT 5.5 (high)",
        "agent": "mini-SWE-agent",
        "resolved_rate": 0.005,
        "almost_resolved_rate": 0.05,
        "average_cost_usd": 3.65,
        "average_calls": 41,
        "source": "https://programbench.com/extended/",
    },
]


def as_bool(value: str) -> bool:
    return value.lower() == "true"


def as_int(value: str) -> int:
    return int(float(value)) if value else 0


def as_float(value: str) -> float:
    return float(value) if value else 0.0


def read_results(path: Path) -> list[ResultRow]:
    with path.open(newline="") as f:
        return [
            ResultRow(
                instance_id=row["instance_id"],
                run_name=row["run_name"],
                model=row["model"],
                reasoning_effort=row["reasoning_effort"],
                inference_mode=row["inference_mode"],
                paper_compliant=as_bool(row["paper_compliant"]),
                score=as_float(row["score"]),
                resolved=as_bool(row["resolved"]),
                almost_resolved=as_bool(row["almost_resolved"]),
                n_resolved_tests=as_int(row["n_resolved_tests"]),
                n_tests=as_int(row["n_tests"]),
                calls=as_int(row["calls"]),
                wall_clock_seconds=as_int(row["wall_clock_seconds"]),
                estimated_cost_usd=as_float(row["estimated_cost_usd"]),
                host_system=row["host_system"],
                host_machine=row["host_machine"],
                docker_cpus=row["docker_cpus"],
                docker_memory=row["docker_memory"],
                pricing_source=row["pricing_source"],
            )
            for row in csv.DictReader(f)
        ]


def aggregate(rows: list[ResultRow]) -> dict:
    return {
        "instances": len(rows),
        "resolved": sum(row.resolved for row in rows),
        "almost_resolved": sum(row.almost_resolved for row in rows),
        "resolved_rate": sum(row.resolved for row in rows) / len(rows) if rows else 0,
        "almost_resolved_rate": sum(row.almost_resolved for row in rows) / len(rows) if rows else 0,
        "average_pass_rate": sum(row.score for row in rows) / len(rows) if rows else 0,
        "total_calls": sum(row.calls for row in rows),
        "average_calls": sum(row.calls for row in rows) / len(rows) if rows else 0,
        "total_cost_usd": sum(row.estimated_cost_usd for row in rows),
        "average_cost_usd": sum(row.estimated_cost_usd for row in rows) / len(rows) if rows else 0,
        "total_wall_clock_hours": sum(row.wall_clock_seconds for row in rows) / 3600,
    }


def row_to_dict(row: ResultRow) -> dict:
    return {
        "instance_id": row.instance_id,
        "run_name": row.run_name,
        "model": row.model,
        "reasoning_effort": row.reasoning_effort,
        "inference_mode": row.inference_mode,
        "paper_compliant": row.paper_compliant,
        "score": row.score,
        "resolved": row.resolved,
        "almost_resolved": row.almost_resolved,
        "n_resolved_tests": row.n_resolved_tests,
        "n_tests": row.n_tests,
        "calls": row.calls,
        "wall_clock_seconds": row.wall_clock_seconds,
        "estimated_cost_usd": row.estimated_cost_usd,
        "host_system": row.host_system,
        "host_machine": row.host_machine,
        "docker_cpus": row.docker_cpus,
        "docker_memory": row.docker_memory,
        "pricing_source": row.pricing_source,
    }


def percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def money(value: float) -> str:
    return f"${value:.2f}"


def cell(value: str) -> str:
    return html.escape(value)


def render_summary_cards(label: str, summary: dict) -> str:
    return f"""
      <section class="summary-card">
        <div class="summary-title">{cell(label)}</div>
        <div class="metric-grid">
          <div><strong>{summary["instances"]}</strong><span>instances</span></div>
          <div><strong>{percent(summary["resolved_rate"])}</strong><span>resolved</span></div>
          <div><strong>{percent(summary["almost_resolved_rate"])}</strong><span>almost</span></div>
          <div><strong>{percent(summary["average_pass_rate"])}</strong><span>avg pass</span></div>
          <div><strong>{money(summary["total_cost_usd"])}</strong><span>cost</span></div>
          <div><strong>{summary["total_calls"]:,}</strong><span>calls</span></div>
        </div>
      </section>
    """


def render_leaderboard(track_summaries: dict[str, dict]) -> str:
    rows = []
    for label, summary in sorted(
        track_summaries.items(),
        key=lambda item: (item[1]["resolved_rate"], item[1]["almost_resolved_rate"], item[1]["average_pass_rate"]),
        reverse=True,
    ):
        rows.append(
            f"""
            <tr>
              <td>{cell(label)}</td>
              <td>{summary["instances"]}</td>
              <td>{percent(summary["resolved_rate"])}</td>
              <td>{percent(summary["almost_resolved_rate"])}</td>
              <td>{percent(summary["average_pass_rate"])}</td>
              <td>{money(summary["average_cost_usd"])}</td>
              <td>{summary["average_calls"]:.1f}</td>
            </tr>
            """
        )
    return "\n".join(rows)


def render_instances(rows: list[ResultRow]) -> str:
    table_rows = []
    for index, row in enumerate(sorted(rows, key=lambda item: item.score, reverse=True), start=1):
        status = "resolved" if row.resolved else "almost" if row.almost_resolved else "open"
        table_rows.append(
            f"""
            <tr>
              <td>{index}</td>
              <td><code>{cell(row.instance_id)}</code></td>
              <td>{cell(row.inference_mode)}</td>
              <td>{cell(row.model)} / {cell(row.reasoning_effort)}</td>
              <td><span class="status {status}">{status}</span></td>
              <td>{percent(row.score)}</td>
              <td>{row.n_resolved_tests}/{row.n_tests}</td>
              <td>{money(row.estimated_cost_usd)}</td>
              <td>{row.calls}</td>
              <td>{row.wall_clock_seconds / 3600:.2f}h</td>
              <td>{cell(row.host_system)}/{cell(row.host_machine)}</td>
              <td>{cell(row.docker_cpus)} CPU / {cell(row.docker_memory)}</td>
            </tr>
            """
        )
    return "\n".join(table_rows)


def render_baselines() -> str:
    return "\n".join(
        f"""
        <tr>
          <td>{cell(str(row["model"]))}</td>
          <td>{cell(str(row["agent"]))}</td>
          <td>{percent(float(row["resolved_rate"]))}</td>
          <td>{percent(float(row["almost_resolved_rate"]))}</td>
          <td>{money(float(row["average_cost_usd"]))}</td>
          <td>{row["average_calls"]}</td>
        </tr>
        """
        for row in BASELINES
    )


def render_html(data: dict) -> str:
    track_cards = "\n".join(render_summary_cards(label, summary) for label, summary in data["tracks"].items())
    instances = [ResultRow(**row) for row in data["rows"]]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ProgramBench Goal Runner Results</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #182026;
      --muted: #61707d;
      --line: #d9e0e6;
      --soft: #f5f7f8;
      --accent: #0f766e;
      --warn: #b45309;
      --bad: #9f1239;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: #ffffff;
    }}
    header {{
      border-bottom: 1px solid var(--line);
      padding: 28px max(24px, calc((100vw - 1180px) / 2));
    }}
    main {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 24px;
    }}
    h1 {{ margin: 0 0 8px; font-size: 28px; letter-spacing: 0; }}
    h2 {{ margin: 32px 0 12px; font-size: 18px; letter-spacing: 0; }}
    p {{ color: var(--muted); line-height: 1.5; max-width: 900px; }}
    .pill-row {{ display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }}
    .pill {{
      border: 1px solid var(--line);
      background: var(--soft);
      padding: 5px 9px;
      border-radius: 6px;
      font-size: 13px;
      color: var(--muted);
    }}
    .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    .summary-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      background: #fff;
    }}
    .summary-title {{ font-weight: 700; margin-bottom: 12px; }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }}
    .metric-grid div {{
      background: var(--soft);
      border-radius: 6px;
      padding: 10px;
      min-height: 62px;
    }}
    .metric-grid strong {{ display: block; font-size: 19px; }}
    .metric-grid span {{ display: block; color: var(--muted); font-size: 12px; margin-top: 4px; }}
    .table-wrap {{
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow-x: auto;
      background: #fff;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 820px;
    }}
    th, td {{
      text-align: left;
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
      font-size: 13px;
      vertical-align: middle;
    }}
    th {{ background: var(--soft); color: #33424d; font-weight: 700; }}
    tr:last-child td {{ border-bottom: 0; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }}
    .status {{
      display: inline-block;
      min-width: 68px;
      border-radius: 999px;
      padding: 3px 8px;
      font-weight: 700;
      font-size: 12px;
      text-align: center;
      background: var(--soft);
    }}
    .status.resolved {{ color: #065f46; background: #d1fae5; }}
    .status.almost {{ color: var(--warn); background: #fef3c7; }}
    .status.open {{ color: var(--bad); background: #ffe4e6; }}
    .note {{
      border-left: 4px solid var(--accent);
      background: #ecfdf5;
      padding: 12px 14px;
      border-radius: 6px;
      color: #134e4a;
    }}
    a {{ color: #075985; }}
  </style>
</head>
<body>
  <header>
    <h1>ProgramBench Goal Runner Results</h1>
    <p>Codex <code>/goal</code> scaffold results on ProgramBench tasks. These are scaffold measurements, not official mini-SWE-agent leaderboard submissions.</p>
    <div class="pill-row">
      <span class="pill">Generated {cell(data["generated_at"])}</span>
      <span class="pill">{data["overall"]["instances"]} evaluated instances</span>
      <span class="pill">Resolved {percent(data["overall"]["resolved_rate"])}</span>
      <span class="pill">Almost {percent(data["overall"]["almost_resolved_rate"])}</span>
    </div>
  </header>
  <main>
    <p class="note">Open-internet runs are intentionally non-compliant with ProgramBench cleanroom rules and are reported separately. Paper-mode smoke runs here may still be local-resource checks unless host/resources say Linux amd64 with 20 CPU / 60g and strict egress.</p>
    <div class="cards">
      {render_summary_cards("Overall", data["overall"])}
      {track_cards}
    </div>

    <h2>Leaderboard</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Track</th><th>Instances</th><th>Resolved</th><th>Almost</th><th>Avg pass</th><th>Avg cost</th><th>Avg calls</th></tr></thead>
        <tbody>{render_leaderboard(data["tracks"])}</tbody>
      </table>
    </div>

    <h2>Per-Instance Results</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>#</th><th>Instance</th><th>Mode</th><th>Model</th><th>Status</th><th>Score</th><th>Tests</th><th>Cost</th><th>Calls</th><th>Wall</th><th>Host</th><th>Docker</th></tr></thead>
        <tbody>{render_instances(instances)}</tbody>
      </table>
    </div>

    <h2>Official Baseline Context</h2>
    <p>For orientation only. ProgramBench's public extended table reports mini-SWE-agent over 200 tasks, sorted by resolved, almost-resolved, then average pass rate.</p>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Model</th><th>Agent</th><th>Resolved</th><th>Almost</th><th>Avg cost</th><th>Avg calls</th></tr></thead>
        <tbody>{render_baselines()}</tbody>
      </table>
    </div>

    <h2>Method Notes</h2>
    <p>Metrics use ProgramBench's resolved and almost-resolved shape. Cost is estimated from Codex token logs and the locally refreshed OpenAI model pricing snapshot; it is not authoritative billing. The committed data omits local session-log paths.</p>
    <p>Sources: <a href="https://programbench.com/extended/">ProgramBench extended results</a>, <a href="https://programbench.com/run/gpt-5-5-xhigh/">GPT 5.5 xhigh run detail</a>, and this repository's generated CSV summaries.</p>
  </main>
</body>
</html>
"""


def build(args: argparse.Namespace) -> None:
    rows = [row for path in args.results_csv for row in read_results(Path(path).expanduser())]
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": aggregate(rows),
        "tracks": {
            label: aggregate([row for row in rows if row.inference_mode == mode])
            for label, mode in {
                "Paper / cleanroom": "paper",
                "Open internet": "open-internet",
            }.items()
            if any(row.inference_mode == mode for row in rows)
        },
        "rows": [row_to_dict(row) for row in rows],
        "baselines": BASELINES,
    }
    output_dir = Path(args.output_dir).expanduser()
    (output_dir / "data").mkdir(parents=True, exist_ok=True)
    (output_dir / "data" / "results.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    (output_dir / "index.html").write_text(render_html(data))
    print(output_dir / "index.html")
    print(output_dir / "data" / "results.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static ProgramBench /goal report site")
    parser.add_argument("results_csv", nargs="+")
    parser.add_argument("--output-dir", default="docs")
    build(parser.parse_args())


if __name__ == "__main__":
    main()
