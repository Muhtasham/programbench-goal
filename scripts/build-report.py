#!/usr/bin/env python3
# ruff: noqa: E501
from __future__ import annotations

import argparse
import csv
import html
import json
import re
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.request import Request, urlopen

AGENT_NAME = "Codex /goal"
PROGRAMBENCH_TASKS = 200
PROGRAMBENCH_EXTENDED = "https://programbench.com/extended/"
TARGET_BASELINE_MODELS = {"GPT 5.5 (xhigh)", "GPT 5.5 (high)"}
ROW_RE = re.compile(r"<tr class=\"clickable-row\".*?</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


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


def slug_text(value: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in value.lower()).strip("-")


def fetch(url: str) -> str:
    with urlopen(Request(url, headers={"User-Agent": "programbench-goal-runner/0.1"}), timeout=30) as response:
        return response.read().decode("utf-8", "replace")


def clean_html(value: str) -> str:
    return " ".join(unescape(TAG_RE.sub(" ", value)).split())


def parse_percent(value: str) -> float:
    return float(value.rstrip("%")) / 100


def parse_money(value: str) -> float:
    return float(value.lstrip("$"))


def parse_baseline_rows(page: str) -> list[dict]:
    rows = []
    for row in ROW_RE.findall(page):
        cells = [clean_html(cell) for cell in CELL_RE.findall(row)]
        if len(cells) < 8 or cells[2] not in TARGET_BASELINE_MODELS:
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
    missing = TARGET_BASELINE_MODELS - {row["model"] for row in rows}
    if missing:
        raise ValueError(f"missing ProgramBench baseline rows: {sorted(missing)}")
    return rows


def refresh_baselines(output_dir: Path) -> None:
    path = output_dir / "data" / "programbench-baselines.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "source": PROGRAMBENCH_EXTENDED,
                "baselines": parse_baseline_rows(fetch(PROGRAMBENCH_EXTENDED)),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def load_baselines(output_dir: Path) -> list[dict]:
    path = output_dir / "data" / "programbench-baselines.json"
    return json.loads(path.read_text())["baselines"] if path.is_file() else BASELINES


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


def model_display(row: ResultRow) -> str:
    name = row.model.upper().replace("-", " ", 1).replace("-", ".")
    return f"{name} ({row.reasoning_effort})" if row.reasoning_effort else name


def mode_label(row: ResultRow) -> str:
    return "Open internet" if row.inference_mode == "open-internet" else "Paper / cleanroom"


def is_programbench_comparable(row: ResultRow) -> bool:
    return (
        row.inference_mode == "paper"
        and row.host_system == "Linux"
        and row.host_machine in {"x86_64", "AMD64"}
        and row.docker_cpus == "20"
        and row.docker_memory == "60g"
    )


def compliance_label(row: ResultRow) -> str:
    if row.inference_mode == "open-internet":
        return "Non-compliant: internet allowed"
    if is_programbench_comparable(row):
        return "ProgramBench-style"
    return "Local smoke: host/resources differ"


def group_key(row: ResultRow) -> tuple[str, str, str, str]:
    return (model_display(row), AGENT_NAME, mode_label(row), compliance_label(row))


def result_groups(rows: list[ResultRow]) -> list[dict]:
    grouped: dict[tuple[str, str, str, str], list[ResultRow]] = {}
    for row in rows:
        grouped.setdefault(group_key(row), []).append(row)
    groups = [
        {
            "slug": slug_text("-".join(key)),
            "model": key[0],
            "agent": key[1],
            "mode": key[2],
            "compliance": key[3],
            **aggregate(group_rows),
        }
        for key, group_rows in grouped.items()
    ]
    return sorted(
        groups,
        key=lambda item: (item["resolved_rate"], item["almost_resolved_rate"], item["average_pass_rate"]),
        reverse=True,
    )


def row_to_dict(row: ResultRow) -> dict:
    evidence_path = f"evidence/{row.run_name}/{row.instance_id}/manifest.json"
    return {
        "instance_id": row.instance_id,
        "run_name": row.run_name,
        "evidence_path": evidence_path if Path("docs", evidence_path).is_file() else "",
        "model": row.model,
        "model_display": model_display(row),
        "agent": AGENT_NAME,
        "reasoning_effort": row.reasoning_effort,
        "inference_mode": row.inference_mode,
        "mode": mode_label(row),
        "compliance": compliance_label(row),
        "programbench_comparable": is_programbench_comparable(row),
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
          <div><strong>{money(summary["average_cost_usd"])}</strong><span>cost / task</span></div>
          <div><strong>{summary["average_calls"]:.1f}</strong><span>calls / task</span></div>
        </div>
      </section>
    """


def result_count(summary: dict, key: str) -> str:
    return f"{percent(summary[key + '_rate'])} ({summary[key]}/{summary['instances']})"


def render_leaderboard(groups: list[dict]) -> str:
    return "\n".join(
        f"""
            <tr>
              <td>{index}</td>
              <td><a href="run/{cell(str(group["slug"]))}/">{cell(str(group["model"]))}</a></td>
              <td>{cell(str(group["agent"]))}</td>
              <td>{result_count(group, "resolved")}</td>
              <td>{result_count(group, "almost_resolved")}</td>
              <td>{money(group["average_cost_usd"])}</td>
              <td>{group["average_calls"]:.1f}</td>
            </tr>
            """
        for index, group in enumerate(groups, start=1)
    )


def render_disclosures(groups: list[dict]) -> str:
    return "\n".join(
        f"""
            <tr>
              <td>{index}</td>
              <td>{cell(str(group["model"]))}</td>
              <td>{cell(str(group["mode"]))}</td>
              <td>{cell(str(group["compliance"]))}</td>
              <td>{group["instances"]}/{PROGRAMBENCH_TASKS}</td>
              <td>{percent(group["average_pass_rate"])}</td>
              <td>{group["total_wall_clock_hours"]:.2f}h</td>
            </tr>
            """
        for index, group in enumerate(groups, start=1)
    )


def render_instances(rows: list[ResultRow]) -> str:
    table_rows = []
    for index, row in enumerate(
        sorted(rows, key=lambda item: (item.resolved, item.almost_resolved, item.score), reverse=True), start=1
    ):
        status = "resolved" if row.resolved else "almost" if row.almost_resolved else "open"
        table_rows.append(
            f"""
            <tr>
              <td>{index}</td>
              <td><code>{cell(row.instance_id)}</code></td>
              <td>{cell(mode_label(row))}</td>
              <td>{cell(model_display(row))}</td>
              <td>{cell(compliance_label(row))}</td>
              <td><span class="status {status}">{status}</span></td>
              <td>{percent(row.score)}</td>
              <td>{row.n_resolved_tests}/{row.n_tests}</td>
              <td>{money(row.estimated_cost_usd)}</td>
              <td>{row.calls}</td>
              <td>{row.wall_clock_seconds / 3600:.2f}h</td>
              <td>{cell(row.host_system)}/{cell(row.host_machine)}</td>
              <td>{cell(row.docker_cpus)} CPU / {cell(row.docker_memory)}</td>
              <td>{evidence_links(row)}</td>
            </tr>
            """
        )
    return "\n".join(table_rows)


def evidence_links(row: ResultRow, prefix: str = "") -> str:
    base = f"evidence/{row.run_name}/{row.instance_id}"
    links = [
        (f"{base}/manifest.json", "manifest"),
        (f"{base}/eval.json", "eval json"),
        (f"{base}/eval-summary.json", "eval summary"),
        (f"{base}/usage-audit.json", "usage audit"),
    ]
    return " · ".join(
        f'<a href="{cell(prefix + path)}">{label}</a>' for path, label in links if Path("docs", path).is_file()
    )


def render_baselines(baselines: list[dict]) -> str:
    return "\n".join(
        f"""
        <tr>
          <td>{index}</td>
          <td>{cell(str(row["model"]))}</td>
          <td>{cell(str(row["agent"]))}</td>
          <td>{percent(float(row["resolved_rate"]))}</td>
          <td>{percent(float(row["almost_resolved_rate"]))}</td>
          <td>{money(float(row["average_cost_usd"]))}</td>
          <td>{row["average_calls"]}</td>
        </tr>
        """
        for index, row in enumerate(baselines, start=1)
    )


def render_csv(rows: list[ResultRow]) -> str:
    output = []
    names = [field.name for field in fields(ResultRow)]
    output.append(",".join(names))
    for row in rows:
        values = []
        for name in names:
            value = getattr(row, name)
            text = str(value)
            values.append('"' + text.replace('"', '""') + '"' if "," in text else text)
        output.append(",".join(values))
    return "\n".join(output) + "\n"


def heat_color(score: float) -> str:
    if score >= 1:
        return "#047857"
    if score >= 0.95:
        return "#d97706"
    if score >= 0.5:
        return "#0f766e"
    if score > 0:
        return "#94a3b8"
    return "#e5e7eb"


def render_run_detail(group: dict, rows: list[ResultRow]) -> str:
    matching = [
        row for row in rows if group_key(row) == (group["model"], group["agent"], group["mode"], group["compliance"])
    ]
    heatmap = "\n".join(
        f'<a class="heat-cell" style="background:{heat_color(row.score)}" title="{cell(row.instance_id)}: {percent(row.score)}" href="../../{evidence_link_path(row)}"></a>'
        for row in sorted(matching, key=lambda item: item.instance_id)
    )
    table = "\n".join(
        f"""
        <tr>
          <td><code>{cell(row.instance_id)}</code></td>
          <td>{percent(row.score)}</td>
          <td>{"yes" if row.resolved else "no"}</td>
          <td>{"yes" if row.almost_resolved else "no"}</td>
          <td>{row.n_resolved_tests}/{row.n_tests}</td>
          <td>{money(row.estimated_cost_usd)}</td>
          <td>{row.calls}</td>
          <td>{evidence_links(row, "../../")}</td>
        </tr>
        """
        for row in sorted(matching, key=lambda item: item.score, reverse=True)
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{cell(str(group["model"]))} ProgramBench /goal Run</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #182026; }}
    a {{ color: #075985; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border-bottom: 1px solid #d9e0e6; padding: 9px 10px; text-align: left; font-size: 13px; }}
    th {{ background: #f5f7f8; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }}
    .heatmap {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(14px, 1fr)); gap: 3px; max-width: 780px; margin: 16px 0; }}
    .heat-cell {{ display: block; aspect-ratio: 1; border-radius: 3px; }}
    .muted {{ color: #61707d; }}
  </style>
</head>
<body>
  <p><a href="../../">← Back to summary</a></p>
  <h1>{cell(str(group["model"]))}</h1>
  <p class="muted">{cell(str(group["agent"]))} · {cell(str(group["mode"]))} · {cell(str(group["compliance"]))}</p>
  <p>Resolved {result_count(group, "resolved")} · Almost {result_count(group, "almost_resolved")} · Avg. pass {percent(group["average_pass_rate"])} · Cost {money(group["average_cost_usd"])} · Calls {group["average_calls"]:.1f}</p>
  <h2>Score by Task</h2>
  <div class="heatmap">{heatmap}</div>
  <table>
    <thead><tr><th>Instance</th><th>Score</th><th>Resolved</th><th>Almost</th><th>Tests</th><th>Cost</th><th>Calls</th><th>Evidence</th></tr></thead>
    <tbody>{table}</tbody>
  </table>
</body>
</html>
"""


def evidence_link_path(row: ResultRow) -> str:
    return f"evidence/{row.run_name}/{row.instance_id}/manifest.json"


def render_comparison(groups: list[dict]) -> str:
    if len(groups) < 2:
        return ""
    rows = []
    for left in groups:
        for right in groups:
            if left is right:
                continue
            rows.append(
                f"""
                <tr>
                  <td>{cell(str(left["model"]))}</td>
                  <td>{cell(str(right["model"]))}</td>
                  <td>{percent(left["resolved_rate"] - right["resolved_rate"])}</td>
                  <td>{percent(left["almost_resolved_rate"] - right["almost_resolved_rate"])}</td>
                  <td>{percent(left["average_pass_rate"] - right["average_pass_rate"])}</td>
                </tr>
                """
            )
    return f"""
    <h2>Model Comparison</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>Y model</th><th>X model</th><th>Resolved Δ</th><th>Almost Δ</th><th>Avg. pass Δ</th></tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>
    """


def render_html(data: dict) -> str:
    group_cards = "\n".join(
        render_summary_cards(
            f"{group['model']} / {group['mode']}",
            group,
        )
        for group in data["groups"]
    )
    result_fields = {field.name for field in fields(ResultRow)}
    instances = [
        ResultRow(**{key: value for key, value in row.items() if key in result_fields}) for row in data["rows"]
    ]
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
      <span class="pill">{data["sample_instances"]} evaluated sample instances</span>
      <span class="pill">{PROGRAMBENCH_TASKS} tasks in full ProgramBench</span>
      <span class="pill">Sorted Resolved → Almost → Avg. pass</span>
    </div>
  </header>
  <main>
    <p class="note">Primary metric is fully resolved instances. Almost resolved follows ProgramBench's displayed threshold of at least 95% behavioral tests passing. Open-internet runs are intentionally non-compliant with ProgramBench cleanroom rules and are reported separately from paper/cleanroom runs.</p>
    <p><a href="data/results.json">Download results.json</a> · <a href="data/results.csv">Download results.csv</a></p>
    <div class="cards">
      {group_cards}
    </div>

    <h2>Extended Results</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>#</th><th>Model</th><th>Agent</th><th>Resolved</th><th>Almost</th><th>Cost</th><th>Calls</th></tr></thead>
        <tbody>{render_leaderboard(data["groups"])}</tbody>
      </table>
    </div>
    <p>Columns mirror ProgramBench's extended leaderboard: resolved and almost-resolved rates, average API cost per task instance, and average calls per task instance. Rows are sorted by resolved, almost-resolved, then average pass rate.</p>

    <h2>Run Disclosures</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>#</th><th>Model</th><th>Mode</th><th>Compliance</th><th>Tasks</th><th>Avg. pass</th><th>Wall</th></tr></thead>
        <tbody>{render_disclosures(data["groups"])}</tbody>
      </table>
    </div>
    <p>These disclosure fields are intentionally outside the mirrored metric table because ProgramBench's public leaderboard does not mix scaffold deviations into the metric columns.</p>

    {render_comparison(data["groups"])}

    <h2>Per-Instance Results</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>#</th><th>Instance</th><th>Mode</th><th>Model</th><th>Compliance</th><th>Status</th><th>Score</th><th>Tests</th><th>Cost</th><th>Calls</th><th>Wall</th><th>Host</th><th>Docker</th><th>Evidence</th></tr></thead>
        <tbody>{render_instances(instances)}</tbody>
      </table>
    </div>

    <h2>Official Baseline Context</h2>
    <p>For orientation only. ProgramBench's public extended table reports mini-SWE-agent over 200 tasks, sorted by resolved, almost-resolved, then average pass rate.</p>
    <div class="table-wrap">
      <table>
        <thead><tr><th>#</th><th>Model</th><th>Agent</th><th>Resolved</th><th>Almost</th><th>Cost</th><th>Calls</th></tr></thead>
        <tbody>{render_baselines(data["baselines"])}</tbody>
      </table>
    </div>

    <h2>Method Notes</h2>
    <p>Metrics use ProgramBench's resolved, almost-resolved, average pass rate, cost, and calls shape. Resolved requires every scored test to pass with no evaluator errors. Local smoke runs are not ProgramBench-comparable until they run on Linux amd64 with 20 CPU / 60g and strict egress. Public evidence manifests include sanitized eval summaries and package contents. Raw Codex session logs and submission tarballs stay local by default. Cost is estimated from Codex token logs and the locally refreshed OpenAI model pricing snapshot; it is not authoritative billing. The committed data omits local session-log paths.</p>
    <p>Sources: <a href="https://programbench.com/extended/">ProgramBench extended results</a>, <a href="https://programbench.com/run/gpt-5-5-xhigh/">GPT 5.5 xhigh run detail</a>, and this repository's generated CSV summaries.</p>
  </main>
</body>
</html>
"""


def build(args: argparse.Namespace) -> None:
    rows = [row for path in args.results_csv for row in read_results(Path(path).expanduser())]
    output_dir = Path(args.output_dir).expanduser()
    if args.refresh_baselines:
        refresh_baselines(output_dir)
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_instances": len(rows),
        "programbench_tasks": PROGRAMBENCH_TASKS,
        "groups": result_groups(rows),
        "rows": [row_to_dict(row) for row in rows],
        "baselines": load_baselines(output_dir),
    }
    (output_dir / "data").mkdir(parents=True, exist_ok=True)
    (output_dir / "data" / "results.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    (output_dir / "data" / "results.csv").write_text(render_csv(rows))
    (output_dir / "index.html").write_text(render_html(data))
    for group in data["groups"]:
        run_dir = output_dir / "run" / str(group["slug"])
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "index.html").write_text(render_run_detail(group, rows))
    print(output_dir / "index.html")
    print(output_dir / "data" / "results.json")
    print(output_dir / "data" / "results.csv")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static ProgramBench /goal report site")
    parser.add_argument("results_csv", nargs="+")
    parser.add_argument("--output-dir", default="docs")
    parser.add_argument(
        "--refresh-baselines",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fetch latest ProgramBench public baseline rows before rendering.",
    )
    build(parser.parse_args())


if __name__ == "__main__":
    main()
