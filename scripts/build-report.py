#!/usr/bin/env python3
# ruff: noqa: E501
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import shutil
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from html import unescape
from itertools import groupby
from pathlib import Path
from statistics import mean, stdev
from urllib.request import Request, urlopen

AGENT_NAME = "Codex /goal"
SITE_NAME = "ProgramBench Goal"
PROGRAMBENCH_TASKS = 200
PROGRAMBENCH_EXTENDED = "https://programbench.com/extended/"
ROW_RE = re.compile(r"<tr class=\"clickable-row\".*?</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class ResultRow:
    instance_id: str
    run_name: str
    run_version: str
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
    with urlopen(Request(url, headers={"User-Agent": "programbench-goal/0.1"}), timeout=30) as response:
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
        if len(cells) < 8:
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
    if len(rows) < 2:
        raise ValueError("could not parse ProgramBench baseline rows")
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


def load_task_baselines(output_dir: Path) -> dict:
    path = output_dir / "data" / "programbench-task-baselines.json"
    return json.loads(path.read_text())["tasks"] if path.is_file() else {}


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
                run_version=row.get("run_version", ""),
                model=row["model"],
                reasoning_effort=row["reasoning_effort"],
                inference_mode=row["inference_mode"],
                paper_compliant=as_bool(row.get("paper_compliant", "")),
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
                pricing_source=row.get("pricing_source", ""),
            )
            for row in csv.DictReader(f)
        ]


def read_target_ids(path: Path) -> list[str]:
    if not path.is_file():
        return []
    return [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]


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


def stddev(values: list[float]) -> float:
    return stdev(values) if len(values) > 1 else 0


def model_display(row: ResultRow) -> str:
    name = row.model.upper().replace("-", " ", 1).replace("-", ".")
    return f"{name} ({row.reasoning_effort})" if row.reasoning_effort else name


def mode_label(row: ResultRow) -> str:
    if row.inference_mode == "paper":
        return "Paper / cleanroom" if is_programbench_comparable(row) else "Paper-mode prompt"
    return {
        "no-internet": "No internet",
        "no-internet-local-tools": "No internet + local tools",
        "open-internet": "Open internet",
    }.get(row.inference_mode, row.inference_mode or "Unknown")


def is_programbench_comparable(row: ResultRow) -> bool:
    return (
        row.inference_mode == "paper"
        and row.paper_compliant
        and row.host_system == "Linux"
        and row.host_machine in {"x86_64", "AMD64"}
        and row.docker_cpus == "20"
        and row.docker_memory == "60g"
    )


def compliance_label(row: ResultRow) -> str:
    if row.inference_mode == "open-internet":
        return "Non-compliant: internet allowed"
    if row.inference_mode == "no-internet":
        return "Codex no-internet ablation"
    if row.inference_mode == "no-internet-local-tools":
        return "Non-compliant: local/binary tools allowed"
    if is_programbench_comparable(row):
        return "ProgramBench-style"
    return "Local smoke: host/resources differ"


def group_key(row: ResultRow) -> tuple[str, str, str, str, str]:
    return (model_display(row), AGENT_NAME, mode_label(row), compliance_label(row), row.run_version)


def result_groups(rows: list[ResultRow]) -> list[dict]:
    grouped = ((key, list(group_rows)) for key, group_rows in groupby(sorted(rows, key=group_key), key=group_key))
    groups = [
        {
            "slug": slug_text("-".join(key)),
            "model": key[0],
            "agent": key[1],
            "mode": key[2],
            "compliance": key[3],
            "run_version": key[4],
            "score_distribution": distribution_bins(group_rows),
            **aggregate(group_rows),
        }
        for key, group_rows in grouped
    ]
    return sorted(
        groups,
        key=lambda item: (item["resolved_rate"], item["almost_resolved_rate"], item["average_pass_rate"]),
        reverse=True,
    )


def repeatability_groups(rows: list[ResultRow]) -> list[dict]:
    grouped = groupby(
        sorted(rows, key=lambda row: (row.instance_id, model_display(row), mode_label(row), compliance_label(row))),
        key=lambda row: (row.instance_id, model_display(row), mode_label(row), compliance_label(row)),
    )
    repeated = []
    for key, group_rows in grouped:
        attempts = list(group_rows)
        versions = sorted({version_label(row.run_version) for row in attempts})
        if len(versions) < 2:
            continue
        scores = [row.score for row in attempts]
        costs = [row.estimated_cost_usd for row in attempts]
        calls = [float(row.calls) for row in attempts]
        walls = [row.wall_clock_seconds / 3600 for row in attempts]
        repeated.append(
            {
                "instance_id": key[0],
                "model": key[1],
                "mode": key[2],
                "compliance": key[3],
                "attempts": len(attempts),
                "versions": versions,
                "score_mean": mean(scores),
                "score_stdev": stddev(scores),
                "score_delta": max(scores) - min(scores),
                "score_min": min(scores),
                "score_max": max(scores),
                "cost_mean": mean(costs),
                "cost_stdev": stddev(costs),
                "calls_mean": mean(calls),
                "calls_stdev": stddev(calls),
                "wall_mean_hours": mean(walls),
                "wall_stdev_hours": stddev(walls),
                "resolved_attempts": sum(row.resolved for row in attempts),
                "almost_attempts": sum(row.almost_resolved for row in attempts),
            }
        )
    return sorted(repeated, key=lambda item: (item["score_delta"], item["score_stdev"]), reverse=True)


def repeatability_summary(repeated: list[dict]) -> dict:
    return {
        "repeated_cells": len(repeated),
        "attempts": sum(item["attempts"] for item in repeated),
        "average_score_stdev": mean([item["score_stdev"] for item in repeated]) if repeated else 0,
        "max_score_delta": max([item["score_delta"] for item in repeated], default=0),
        "average_cost_stdev": mean([item["cost_stdev"] for item in repeated]) if repeated else 0,
        "average_calls_stdev": mean([item["calls_stdev"] for item in repeated]) if repeated else 0,
    }


def row_to_dict(row: ResultRow) -> dict:
    evidence_path = f"evidence/{row.run_name}/{row.instance_id}/manifest.json"
    return {
        "instance_id": row.instance_id,
        "run_name": row.run_name,
        "run_version": row.run_version,
        "evidence_path": evidence_path if Path("docs", evidence_path).is_file() else "",
        "task_path": f"task/{row.instance_id}/",
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


def task_groups(rows: list[ResultRow], target_ids: list[str], official_tasks: dict) -> list[dict]:
    row_groups = {
        instance_id: list(group_rows)
        for instance_id, group_rows in groupby(
            sorted(rows, key=lambda row: row.instance_id), key=lambda row: row.instance_id
        )
    }
    instance_ids = target_ids or sorted(row_groups)
    return [
        {
            "instance_id": instance_id,
            "task_path": f"task/{instance_id}/",
            "official_task_url": f"https://programbench.com/task/{instance_id}/",
            "result_count": len(task_rows),
            "scored_tests": max((row.n_tests for row in task_rows), default=None),
            "best_score": max((row.score for row in task_rows), default=None),
            "best_model": model_display(max(task_rows, key=lambda row: row.score)) if task_rows else "",
            "official_generated_tests": official_tasks.get(instance_id, {}).get("generated_tests"),
            "official_best_score": official_tasks.get(instance_id, {}).get("best_score"),
            "official_result_count": len(official_tasks.get(instance_id, {}).get("results", [])),
        }
        for instance_id in instance_ids
        for task_rows in [row_groups.get(instance_id, [])]
    ]


def percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def money(value: float) -> str:
    return f"${value:.2f}"


def whole_money(value: float) -> str:
    return f"${value:,.0f}" if value >= 100 else money(value)


def integer(value: float | int) -> str:
    return f"{value:,.0f}"


def cell(value: str) -> str:
    return html.escape(value)


def plot_points(rows: list[ResultRow], x_value, x_label: str, x_format) -> str:
    width = 360
    height = 220
    left = 42
    right = 18
    top = 18
    bottom = 34
    plot_width = width - left - right
    plot_height = height - top - bottom
    values = [x_value(row) for row in rows]
    max_x = max(values) if values else 1
    max_x = max_x or 1
    return f"""
      <svg class="plot" viewBox="0 0 {width} {height}" role="img" aria-label="Pass rate by {cell(x_label)}">
        <line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" />
        <line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" />
        <text x="{left - 8}" y="{top + 4}" text-anchor="end">100%</text>
        <text x="{left - 8}" y="{top + plot_height + 4}" text-anchor="end">0%</text>
        <text x="{left}" y="{height - 8}">0</text>
        <text x="{left + plot_width}" y="{height - 8}" text-anchor="end">{cell(x_format(max_x))}</text>
        <text x="{width / 2}" y="{height - 8}" text-anchor="middle">{cell(x_label)}</text>
        <text x="12" y="{height / 2}" transform="rotate(-90 12 {height / 2})" text-anchor="middle">pass rate</text>
        {"".join(plot_circle(row, x_value, x_label, x_format, max_x, left, top, plot_width, plot_height) for row in rows)}
      </svg>
    """


def plot_circle(row: ResultRow, x_value, x_label: str, x_format, max_x, left, top, plot_width, plot_height) -> str:
    x = left + (x_value(row) / max_x) * plot_width
    y = top + (1 - row.score) * plot_height
    title = (
        f"{row.instance_id}: {percent(row.score)} pass, {x_label.lower()} {x_format(x_value(row))}, {mode_label(row)}"
    )
    color = "#047857" if row.resolved else "#d97706" if row.almost_resolved else "#be123c"
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="{color}"><title>{cell(title)}</title></circle>'


def distribution_bins(rows: list[ResultRow]) -> list[dict]:
    counts = [0] * 10
    for row in rows:
        counts[min(int(row.score * 10), 9)] += 1
    return [
        {
            "lower": index / 10,
            "upper": (index + 1) / 10,
            "label": f"{index * 10}-{(index + 1) * 10}%",
            "count": count,
            "cumulative_at_least": sum(counts[index:]),
            "cumulative_rate_at_least": sum(counts[index:]) / len(rows) if rows else 0,
        }
        for index, count in enumerate(counts)
    ]


def distribution_svg(rows: list[ResultRow], cumulative: bool) -> str:
    width = 520
    height = 240
    left = 42
    right = 14
    top = 18
    bottom = 46
    plot_width = width - left - right
    plot_height = height - top - bottom
    bins = distribution_bins(rows)
    values = [item["cumulative_at_least"] if cumulative else item["count"] for item in bins]
    max_y = max(values) if values else 1
    max_y = max_y or 1
    bar_width = plot_width / len(bins)
    bars = []
    for index, item in enumerate(bins):
        value = values[index]
        bar_height = (value / max_y) * plot_height
        x = left + index * bar_width + 2
        y = top + plot_height - bar_height
        title = (
            f"{item['label']} pass: {value} task(s)"
            if not cumulative
            else f">= {item['lower']:.0%} pass: {value} task(s), {percent(item['cumulative_rate_at_least'])}"
        )
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width - 4:.1f}" height="{bar_height:.1f}" fill="#0f766e"><title>{cell(title)}</title></rect>'
        )
    return f"""
      <svg class="plot" viewBox="0 0 {width} {height}" role="img" aria-label="Behavioral test pass rate {"cumulative distribution" if cumulative else "histogram"}">
        <line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_height}" />
        <line x1="{left}" y1="{top + plot_height}" x2="{left + plot_width}" y2="{top + plot_height}" />
        <text x="{left - 8}" y="{top + 4}" text-anchor="end">{max_y}</text>
        <text x="{left - 8}" y="{top + plot_height + 4}" text-anchor="end">0</text>
        <text x="{left}" y="{height - 12}">0%</text>
        <text x="{left + plot_width}" y="{height - 12}" text-anchor="end">100%</text>
        <text x="{width / 2}" y="{height - 12}" text-anchor="middle">behavioral test pass rate</text>
        <text x="12" y="{height / 2}" transform="rotate(-90 12 {height / 2})" text-anchor="middle">tasks</text>
        {"".join(bars)}
      </svg>
    """


def official_distribution_svg(rows: list[dict], cumulative: bool) -> str:
    result_rows = [
        ResultRow(
            instance_id=row["instance_id"],
            run_name="official",
            run_version="",
            model="official",
            reasoning_effort="",
            inference_mode="official",
            paper_compliant=True,
            score=float(row["score"] or 0),
            resolved=row["score"] == 1.0,
            almost_resolved=row["score"] is not None and row["score"] >= 0.95,
            n_resolved_tests=0,
            n_tests=0,
            calls=int(row["calls"]),
            wall_clock_seconds=0,
            estimated_cost_usd=float(row["cost_usd"]),
            host_system="",
            host_machine="",
            docker_cpus="",
            docker_memory="",
            pricing_source="",
        )
        for row in rows
    ]
    return distribution_svg(result_rows, cumulative)


def render_score_distribution(rows: list[ResultRow]) -> str:
    if not rows:
        return ""
    return f"""
    <h2>Behavioral Test Pass Rate Distribution</h2>
    <p>These plots mirror ProgramBench's run-detail views: a score histogram and a cumulative count by behavioral test pass-rate bucket.</p>
    <div class="plot-grid">
      <section class="plot-card">
        <h3>Histogram</h3>
        {distribution_svg(rows, cumulative=False)}
      </section>
      <section class="plot-card">
        <h3>Cumulative</h3>
        {distribution_svg(rows, cumulative=True)}
      </section>
    </div>
    """


def render_efficiency_plots(rows: list[ResultRow]) -> str:
    if not rows:
        return ""
    return f"""
    <h2>Efficiency Plots</h2>
    <p>Each point is one evaluated task. Compute is shown as Codex calls because public results omit raw token logs; cost is estimated from local token logs and a pricing snapshot.</p>
    <div class="plot-grid">
      <section class="plot-card">
        <h3>Pass vs. Est. Cost</h3>
        {plot_points(rows, lambda row: row.estimated_cost_usd, "Est. cost (USD)", money)}
      </section>
      <section class="plot-card">
        <h3>Pass vs. Calls</h3>
        {plot_points(rows, lambda row: row.calls, "Codex calls", lambda value: f"{value:.0f}")}
      </section>
      <section class="plot-card">
        <h3>Pass vs. Latency</h3>
        {plot_points(rows, lambda row: row.wall_clock_seconds / 3600, "Wall-clock hours", lambda value: f"{value:.2f}h")}
      </section>
    </div>
    """


def pending_plot(title: str, x_label: str) -> str:
    return f"""
      <section class="plot-card pending-plot">
        <h3>{cell(title)}</h3>
        <svg class="plot" viewBox="0 0 360 220" role="img" aria-label="{cell(title)} pending results">
          <line x1="42" y1="18" x2="42" y2="186" />
          <line x1="42" y1="186" x2="342" y2="186" />
          <text x="34" y="22" text-anchor="end">100%</text>
          <text x="34" y="190" text-anchor="end">0%</text>
          <text x="192" y="212" text-anchor="middle">{cell(x_label)}</text>
          <text x="12" y="110" transform="rotate(-90 12 110)" text-anchor="middle">pass rate</text>
          <text x="192" y="106" text-anchor="middle">waiting for results</text>
        </svg>
      </section>
    """


def render_pending_charts() -> str:
    return f"""
    <h2>Score by Model × Task</h2>
    <p>The matrix below mirrors ProgramBench's all-models-by-all-tasks view for this scaffold. Cells are pending until Codex results are published, then link to task pages with per-task detail.</p>
    <div class="score-matrix pending-matrix">
      {"".join('<a class="heat-cell pending" title="pending"></a>' for _ in range(PROGRAMBENCH_TASKS))}
    </div>
    <h2>Behavioral Test Pass Rate Distribution</h2>
    <p>The distribution plots are wired into the report. They stay empty until the first evaluated task lands, then render ProgramBench-style cumulative and histogram views.</p>
    <div class="plot-grid">
      {pending_plot("Cumulative", "behavioral test pass rate")}
      {pending_plot("Histogram", "behavioral test pass rate")}
    </div>
    <h2>Model Comparison</h2>
    <p>Model comparison plots appear once there are at least two Codex result groups. Each dot will be one task instance, matching ProgramBench's comparison framing.</p>
    <div class="plot-grid">
      {pending_plot("Model Comparison", "comparison score")}
    </div>
    <h2>Efficiency Plots</h2>
    <p>The chart slots are wired into the report. They stay empty until the first evaluated task lands, then render ProgramBench-style pass-rate distribution plus pass rate by cost, calls, and latency.</p>
    <div class="plot-grid">
      {pending_plot("Pass vs. Est. Cost", "estimated cost")}
      {pending_plot("Pass vs. Calls", "Codex calls")}
      {pending_plot("Pass vs. Latency", "wall-clock hours")}
    </div>
    """


def render_summary_cards(label: str, summary: dict) -> str:
    return f"""
      <section class="summary-card">
        <div class="summary-title">{cell(label)}</div>
        <div class="summary-meta">{cell(str(summary["compliance"]))} · run {cell(version_label(str(summary.get("run_version", ""))))}</div>
        <div class="metric-grid">
          <div><strong>{summary["instances"]}</strong><span>instances</span></div>
          <div><strong>{percent(summary["resolved_rate"])}</strong><span>resolved</span></div>
          <div><strong>{percent(summary["almost_resolved_rate"])}</strong><span>almost</span></div>
          <div><strong>{percent(summary["average_pass_rate"])}</strong><span>avg pass</span></div>
          <div><strong>{whole_money(summary["total_cost_usd"])}</strong><span>total est. cost</span></div>
          <div><strong>{integer(summary["total_calls"])}</strong><span>total calls</span></div>
          <div><strong>{money(summary["average_cost_usd"])}</strong><span>est. cost / task</span></div>
          <div><strong>{summary["average_calls"]:.1f}</strong><span>calls / task</span></div>
        </div>
      </section>
    """


def result_count(summary: dict, key: str) -> str:
    return f"{percent(summary[key + '_rate'])} ({summary[key]}/{summary['instances']})"


def run_metric_cards(group: dict) -> str:
    return f"""
    <div class="metric-grid">
      <div><strong>{percent(group["resolved_rate"])}</strong><span>resolved</span></div>
      <div><strong>{percent(group["almost_resolved_rate"])}</strong><span>almost resolved</span></div>
      <div><strong>{whole_money(group["total_cost_usd"])}</strong><span>total est. cost</span></div>
      <div><strong>{integer(group["total_calls"])}</strong><span>total calls</span></div>
    </div>
    """


def version_label(version: str) -> str:
    return version or "unversioned"


def render_leaderboard(groups: list[dict]) -> str:
    return "\n".join(
        f"""
            <tr>
              <td>{index}</td>
              <td><a href="run/{cell(str(group["slug"]))}/">{cell(str(group["model"]))}</a></td>
              <td><code>{cell(version_label(str(group.get("run_version", ""))))}</code></td>
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
              <td><code>{cell(version_label(str(group.get("run_version", ""))))}</code></td>
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
              <td><a href="task/{cell(row.instance_id)}/"><code>{cell(row.instance_id)}</code></a></td>
              <td><code>{cell(version_label(row.run_version))}</code></td>
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


def task_page_link(row: ResultRow, prefix: str = "") -> str:
    return f"{prefix}task/{row.instance_id}/"


def official_run_url(model: str) -> str:
    return {
        "GPT 5.5 (xhigh)": "https://programbench.com/run/gpt-5-5-xhigh/",
        "GPT 5.5 (high)": "https://programbench.com/run/gpt-5-5-high/",
    }.get(model, "")


def render_baselines(baselines: list[dict]) -> str:
    return "\n".join(
        f"""
        <tr>
          <td>{index}</td>
          <td>{baseline_model_link(row)}</td>
          <td>{cell(str(row["agent"]))}</td>
          <td>{percent(float(row["resolved_rate"]))}</td>
          <td>{percent(float(row["almost_resolved_rate"]))}</td>
          <td>{money(float(row["average_cost_usd"]))}</td>
          <td>{row["average_calls"]}</td>
        </tr>
        """
        for index, row in enumerate(baselines, start=1)
    )


def baseline_model_link(row: dict) -> str:
    url = official_run_url(str(row["model"]))
    if url:
        return f'<a href="{cell(url)}">{cell(str(row["model"]))}</a>'
    return cell(str(row["model"]))


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


def render_task_index(tasks: list[dict]) -> str:
    if not tasks:
        return ""
    sorted_tasks = sorted(
        tasks,
        key=lambda item: (item["best_score"] is None, -(item["best_score"] or 0), item["instance_id"]),
    )
    rows = "\n".join(
        f"""
        <tr>
          <td>{index}</td>
          <td><a href="{cell(str(task["task_path"]))}"><code>{cell(str(task["instance_id"]))}</code></a></td>
          <td>{task["official_generated_tests"] if task["official_generated_tests"] is not None else "pending"}</td>
          <td>{percent(float(task["official_best_score"])) if task["official_best_score"] is not None else "pending"}</td>
          <td>{percent(float(task["best_score"])) if task["best_score"] is not None else "pending"}</td>
          <td>{cell(str(task["best_model"] or "pending"))}</td>
          <td>{task["result_count"]}</td>
          <td>{task["official_result_count"]}</td>
          <td><a href="{cell(str(task["official_task_url"]))}">official</a></td>
        </tr>
        """
        for index, task in enumerate(sorted_tasks, start=1)
    )
    return f"""
    <h2>Task Details</h2>
    <p>Task pages mirror ProgramBench's per-task view for this scaffold: scored behavioral tests, best score, and results by model/mode. Pending rows are full-run targets waiting for Codex results. The official ProgramBench task page is linked for baseline context.</p>
    <div class="table-wrap">
      <table>
        <thead><tr><th>#</th><th>Task</th><th>Generated tests</th><th>Official best</th><th>Codex best</th><th>Codex model</th><th>Codex rows</th><th>Official rows</th><th>ProgramBench</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """


def official_task_result_rows(task: dict) -> str:
    return "\n".join(
        f"""
        <tr>
          <td>{index}</td>
          <td>{cell(str(row["model"]))}</td>
          <td>{cell(str(row["provider"]))}</td>
          <td>{percent(float(row["score"])) if row["score"] is not None else "n/a"}</td>
          <td>{money(float(row["cost_usd"]))}</td>
          <td>{integer(int(row["calls"]))}</td>
        </tr>
        """
        for index, row in enumerate(task.get("results", []), start=1)
    )


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
        row
        for row in rows
        if group_key(row)
        == (group["model"], group["agent"], group["mode"], group["compliance"], group.get("run_version", ""))
    ]
    heatmap = "\n".join(
        f'<a class="heat-cell" style="background:{heat_color(row.score)}" title="{cell(row.instance_id)}: {percent(row.score)}" href="../../{task_page_link(row)}"></a>'
        for row in sorted(matching, key=lambda item: item.instance_id)
    )
    table = "\n".join(
        f"""
        <tr>
          <td><a href="../../{task_page_link(row)}"><code>{cell(row.instance_id)}</code></a></td>
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
    .plot-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin: 14px 0 18px; }}
    .plot-card {{ border: 1px solid #d9e0e6; border-radius: 8px; padding: 12px; }}
    .plot {{ width: 100%; height: auto; display: block; }}
    .plot line {{ stroke: #d9e0e6; stroke-width: 1.5; }}
    .plot text {{ fill: #61707d; font-size: 11px; }}
    .muted {{ color: #61707d; }}
  </style>
</head>
<body>
  <p><a href="../../">← Back to summary</a></p>
  <h1>{cell(str(group["model"]))}</h1>
  <p class="muted">{cell(str(group["agent"]))} · run {cell(version_label(str(group.get("run_version", ""))))} · {cell(str(group["mode"]))} · {cell(str(group["compliance"]))}</p>
  {run_metric_cards(group)}
  <p>Avg. pass {percent(group["average_pass_rate"])} · Avg. est. cost / task {money(group["average_cost_usd"])} · Avg. calls / task {group["average_calls"]:.1f}</p>
  {render_score_distribution(matching)}
  <h2>Score by Task</h2>
  <div class="heatmap">{heatmap}</div>
  <table>
    <thead><tr><th>Instance</th><th>Score</th><th>Resolved</th><th>Almost</th><th>Tests</th><th>Est. cost</th><th>Calls</th><th>Evidence</th></tr></thead>
    <tbody>{table}</tbody>
  </table>
</body>
</html>
"""


def evidence_link_path(row: ResultRow) -> str:
    return f"evidence/{row.run_name}/{row.instance_id}/manifest.json"


def render_task_detail(instance_id: str, rows: list[ResultRow], official_tasks: dict) -> str:
    matching = sorted([row for row in rows if row.instance_id == instance_id], key=lambda row: row.score, reverse=True)
    best_score = max((row.score for row in matching), default=None)
    scored_tests = max((row.n_tests for row in matching), default=None)
    official_task_url = f"https://programbench.com/task/{instance_id}/"
    official_task = official_tasks.get(instance_id, {})
    if matching:
        result_rows = "\n".join(
            f"""
        <tr>
          <td>{index}</td>
          <td>{cell(model_display(row))}</td>
          <td><code>{cell(version_label(row.run_version))}</code></td>
          <td>{cell(AGENT_NAME)}</td>
          <td>{cell(mode_label(row))}</td>
          <td>{percent(row.score)}</td>
          <td>{row.n_resolved_tests}/{row.n_tests}</td>
          <td>{money(row.estimated_cost_usd)}</td>
          <td>{row.calls}</td>
          <td>{row.wall_clock_seconds / 3600:.2f}h</td>
          <td>{evidence_links(row, "../../")}</td>
        </tr>
        """
            for index, row in enumerate(matching, start=1)
        )
    else:
        result_rows = """
        <tr>
          <td colspan="11">No Codex results published for this task yet.</td>
        </tr>
        """
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{cell(instance_id)} ProgramBench Task</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 24px; color: #182026; }}
    a {{ color: #075985; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border-bottom: 1px solid #d9e0e6; padding: 9px 10px; text-align: left; font-size: 13px; }}
    th {{ background: #f5f7f8; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; max-width: 780px; margin: 16px 0; }}
    .metric {{ border: 1px solid #d9e0e6; border-radius: 8px; padding: 14px; }}
    .metric strong {{ display: block; font-size: 24px; }}
    .metric span {{ color: #61707d; font-size: 13px; }}
    .muted {{ color: #61707d; }}
  </style>
</head>
<body>
  <p><a href="../../">← Back to summary</a> · <a href="{cell(official_task_url)}">Official ProgramBench task page</a></p>
  <h1><code>{cell(instance_id)}</code></h1>
  <p class="muted">Task-level results for this Codex <code>/goal</code> scaffold. ProgramBench baseline context is cached from the official task page; Codex scored tests are after active-branch and ignored-test filtering.</p>
  <div class="metric-grid">
    <div class="metric"><strong>{official_task.get("generated_tests", scored_tests if scored_tests is not None else "pending")}</strong><span>generated behavioral tests</span></div>
    <div class="metric"><strong>{percent(float(official_task["best_score"])) if official_task.get("best_score") is not None else "pending"}</strong><span>official best score</span></div>
    <div class="metric"><strong>{percent(best_score) if best_score is not None else "pending"}</strong><span>Codex best score</span></div>
    <div class="metric"><strong>{len(matching)}</strong><span>Codex result rows</span></div>
  </div>
  <h2>Codex Results by Model</h2>
  <table>
    <thead><tr><th>#</th><th>Model</th><th>Run</th><th>Agent</th><th>Mode</th><th>Score</th><th>Tests</th><th>Est. cost</th><th>Calls</th><th>Wall</th><th>Evidence</th></tr></thead>
    <tbody>{result_rows}</tbody>
  </table>
  <h2>Official ProgramBench Results by Model</h2>
  <table>
    <thead><tr><th>#</th><th>Model</th><th>Provider</th><th>Score</th><th>Cost</th><th>Calls</th></tr></thead>
    <tbody>{official_task_result_rows(official_task) or '<tr><td colspan="6">Official task rows not cached yet.</td></tr>'}</tbody>
  </table>
</body>
</html>
"""


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


def render_repeatability(data: dict) -> str:
    repeated = data["repeatability"]
    if not repeated:
        return ""
    summary = data["repeatability_summary"]
    rows = "\n".join(
        f"""
        <tr>
          <td>{index}</td>
          <td><a href="task/{cell(str(item["instance_id"]))}/"><code>{cell(str(item["instance_id"]))}</code></a></td>
          <td>{cell(str(item["model"]))}</td>
          <td>{cell(str(item["mode"]))}</td>
          <td>{cell(str(item["compliance"]))}</td>
          <td>{item["attempts"]}</td>
          <td><code>{cell(", ".join(item["versions"]))}</code></td>
          <td>{percent(float(item["score_mean"]))}</td>
          <td>{percent(float(item["score_stdev"]))}</td>
          <td>{percent(float(item["score_delta"]))}</td>
          <td>{money(float(item["cost_mean"]))}</td>
          <td>{money(float(item["cost_stdev"]))}</td>
          <td>{item["calls_mean"]:.1f}</td>
          <td>{item["calls_stdev"]:.1f}</td>
          <td>{item["wall_mean_hours"]:.2f}h</td>
          <td>{item["wall_stdev_hours"]:.2f}h</td>
          <td>{item["resolved_attempts"]}/{item["attempts"]}</td>
          <td>{item["almost_attempts"]}/{item["attempts"]}</td>
        </tr>
        """
        for index, item in enumerate(repeated, start=1)
    )
    return f"""
    <h2>Repeatability / Variance</h2>
    <p>This section appears only when the same task, model, mode, and compliance bucket has results from more than one run version. It keeps repeated sweeps visible instead of collapsing them into one row.</p>
    <div class="cards">
      <section class="summary-card">
        <div class="summary-title">Repeated cells</div>
        <div class="summary-meta">task x model x mode x compliance</div>
        <div class="metric-grid">
          <div><strong>{summary["repeated_cells"]}</strong><span>repeated cells</span></div>
          <div><strong>{summary["attempts"]}</strong><span>attempt rows</span></div>
          <div><strong>{percent(float(summary["average_score_stdev"]))}</strong><span>avg score stdev</span></div>
          <div><strong>{percent(float(summary["max_score_delta"]))}</strong><span>max score delta</span></div>
          <div><strong>{money(float(summary["average_cost_stdev"]))}</strong><span>avg est. cost stdev</span></div>
          <div><strong>{summary["average_calls_stdev"]:.1f}</strong><span>avg calls stdev</span></div>
        </div>
      </section>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>#</th><th>Instance</th><th>Model</th><th>Mode</th><th>Compliance</th><th>Attempts</th><th>Versions</th><th>Mean score</th><th>Score stdev</th><th>Score delta</th><th>Mean cost</th><th>Cost stdev</th><th>Mean calls</th><th>Calls stdev</th><th>Mean wall</th><th>Wall stdev</th><th>Resolved</th><th>Almost</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """


def render_empty_state() -> str:
    return """
    <section class="empty-state">
      <h2>Clean Slate</h2>
      <p>No Codex <code>/goal</code> results are published in this reset yet. The next full run will populate the leaderboard, run-detail pages, task pages, plots, and downloadable JSON/CSV artifacts.</p>
      <div class="mode-grid">
        <div class="mode-card">
          <strong>Primary run</strong>
          <p><code>configs/full-nointernet-xhigh.json</code> measures the Codex scaffold without internet and is the clean default for the Noam/Jake question.</p>
        </div>
        <div class="mode-card">
          <strong>Paper-comparable run</strong>
          <p><code>configs/full-paper-xhigh.json</code> should run only on Linux amd64 with 20 CPU, 60g RAM, strict egress, and wrapper-only target access.</p>
        </div>
        <div class="mode-card">
          <strong>Open-internet ablation</strong>
          <p><code>configs/full-open-xhigh.json</code> is intentionally non-compliant and stays separate from cleanroom results.</p>
        </div>
      </div>
    </section>
    """


def render_results_sections(data: dict, instances: list[ResultRow]) -> str:
    if not instances:
        return f"""
    {render_empty_state()}
    {render_pending_charts()}
    {render_task_index(data["tasks"])}
    """
    return f"""
    <div class="cards">
      {"".join(render_summary_cards(f"{group['model']} / {group['mode']} / {version_label(str(group.get('run_version', '')))}", group) for group in data["groups"])}
    </div>

    <h2>Score by Model × Task</h2>
    <div class="score-matrix">
      {"".join(f'<a class="heat-cell" style="background:{heat_color(row.score)}" title="{cell(row.instance_id)}: {percent(row.score)}" href="{task_page_link(row)}"></a>' for row in sorted(instances, key=lambda row: (model_display(row), row.instance_id)))}
    </div>

    {render_score_distribution(instances)}

    {render_efficiency_plots(instances)}

    <h2>Extended Results</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>#</th><th>Model</th><th>Run</th><th>Agent</th><th>Resolved</th><th>Almost</th><th>Avg. est. cost</th><th>Avg. calls</th></tr></thead>
        <tbody>{render_leaderboard(data["groups"])}</tbody>
      </table>
    </div>
    <p>Columns mirror ProgramBench's extended leaderboard shape: resolved and almost-resolved rates, average estimated API cost per task instance, and average calls per task instance. ProgramBench run-detail pages show total cost and total calls; our run-detail pages do the same. Run versions keep repeated same-config sweeps separate instead of silently merging attempts. Mode and compliance are shown in Run Disclosures and Per-Instance Results so the mirrored metric table stays close to ProgramBench's shape.</p>

    <h2>Run Disclosures</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>#</th><th>Model</th><th>Run</th><th>Mode</th><th>Compliance</th><th>Tasks</th><th>Avg. pass</th><th>Wall</th></tr></thead>
        <tbody>{render_disclosures(data["groups"])}</tbody>
      </table>
    </div>
    <p>These disclosure fields are intentionally outside the mirrored metric table because ProgramBench's public leaderboard does not mix scaffold deviations into the metric columns.</p>

    {render_comparison(data["groups"])}

    {render_repeatability(data)}

    {render_task_index(data["tasks"])}

    <h2>Per-Instance Results</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>#</th><th>Instance</th><th>Run</th><th>Mode</th><th>Model</th><th>Compliance</th><th>Status</th><th>Score</th><th>Tests</th><th>Est. cost</th><th>Calls</th><th>Wall</th><th>Host</th><th>Docker</th><th>Evidence</th></tr></thead>
        <tbody>{render_instances(instances)}</tbody>
      </table>
    </div>
    """


def render_html(data: dict) -> str:
    result_fields = {field.name for field in fields(ResultRow)}
    instances = [
        ResultRow(**{key: value for key, value in row.items() if key in result_fields}) for row in data["rows"]
    ]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{SITE_NAME}</title>
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
    h3 {{ margin: 0 0 10px; font-size: 14px; letter-spacing: 0; }}
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
    .summary-title {{ font-weight: 700; margin-bottom: 4px; }}
    .summary-meta {{ color: var(--muted); font-size: 13px; margin-bottom: 12px; }}
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
    .empty-state {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 18px;
      margin: 20px 0;
    }}
    .empty-state h2 {{ margin-top: 0; }}
    .mode-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 10px;
      margin: 14px 0 18px;
    }}
    .mode-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: var(--soft);
    }}
    .mode-card strong {{ display: block; margin-bottom: 6px; }}
    .mode-card p {{ margin: 0; font-size: 13px; }}
    .plot-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px;
      margin: 14px 0 18px;
    }}
    .plot-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #fff;
    }}
    .plot {{
      width: 100%;
      height: auto;
      display: block;
    }}
    .plot line {{ stroke: var(--line); stroke-width: 1.5; }}
    .plot text {{ fill: var(--muted); font-size: 11px; }}
    .score-matrix {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(12px, 1fr));
      gap: 3px;
      max-width: 920px;
      margin: 14px 0 18px;
    }}
    .heat-cell {{
      display: block;
      aspect-ratio: 1;
      border-radius: 3px;
      background: #e5e7eb;
    }}
    .heat-cell.pending {{
      background: linear-gradient(135deg, #f5f7f8 25%, #e5e7eb 25%, #e5e7eb 50%, #f5f7f8 50%, #f5f7f8 75%, #e5e7eb 75%);
      background-size: 8px 8px;
    }}
    a {{ color: #075985; }}
  </style>
</head>
<body>
  <header>
    <h1>{SITE_NAME}</h1>
    <p>Codex <code>/goal</code> scaffold results on ProgramBench tasks. These are scaffold measurements, not official mini-SWE-agent leaderboard submissions.</p>
    <div class="pill-row">
      <span class="pill">Generated {cell(data["generated_at"])}</span>
      <span class="pill">{data["sample_instances"]} evaluated instances</span>
      <span class="pill">{PROGRAMBENCH_TASKS} tasks in full ProgramBench</span>
      <span class="pill">Sorted Resolved → Almost → Avg. pass</span>
    </div>
  </header>
  <main>
    <p class="note">Primary metric is fully resolved instances. Almost resolved follows ProgramBench's displayed threshold of at least 95% behavioral tests passing. Open-internet runs are intentionally non-compliant with ProgramBench cleanroom rules and are reported separately from paper/cleanroom runs.</p>
    <h2>How To Read Modes</h2>
    <div class="mode-grid">
      <div class="mode-card">
        <strong>No internet</strong>
        <p>Primary Codex <code>/goal</code> scaffold for the Noam/Jake question: internet/source/package lookup blocked and target binary analysis still banned.</p>
      </div>
      <div class="mode-card">
        <strong>Paper / cleanroom</strong>
        <p>Black-box mode matching ProgramBench rules as closely as this scaffold can. Only ProgramBench-comparable on Linux amd64 with 20 CPU / 60g and strict egress.</p>
      </div>
      <div class="mode-card">
        <strong>No internet + local tools</strong>
        <p>Non-compliant ablation for the tool-starvation critique: no external internet/source lookup, but local binary-analysis/tracing tools are allowed.</p>
      </div>
      <div class="mode-card">
        <strong>Open internet</strong>
        <p>Full Codex harness. Internet and package tooling are allowed. Not ProgramBench-compliant.</p>
      </div>
    </div>
    <p><a href="data/results.json">Download results.json</a> · <a href="data/results.csv">Download results.csv</a></p>
    {render_results_sections(data, instances)}

    <h2>Official Baseline Context</h2>
    <p>For orientation only. ProgramBench's public extended table reports mini-SWE-agent over 200 tasks, sorted by resolved, almost-resolved, then average pass rate.</p>
    <div class="table-wrap">
      <table>
        <thead><tr><th>#</th><th>Model</th><th>Agent</th><th>Resolved</th><th>Almost</th><th>Avg. cost</th><th>Avg. calls</th></tr></thead>
        <tbody>{render_baselines(data["baselines"])}</tbody>
      </table>
    </div>
    <p>GPT-5.5 baseline rows link to ProgramBench's official run-detail pages for total cost, total calls, distribution plots, and all 200 per-instance results.</p>

    <h2>Method Notes</h2>
    <p>Metrics use ProgramBench's resolved, almost-resolved, average pass rate, cost, and calls shape. Scoring is computed through ProgramBench's own <code>EvaluationResult</code> and <code>InstanceEvalSummary</code> logic after active-branch and ignored-test filtering. Resolved means the ProgramBench behavioral test pass rate is exactly 100%; evaluator warnings/errors are disclosed separately in evidence artifacts. Local smoke runs are not ProgramBench-comparable until they run on Linux amd64 with 20 CPU / 60g and strict egress. Public evidence manifests include sanitized eval summaries and package contents. Raw Codex session logs and submission tarballs stay local by default. Estimated cost comes from Codex token logs and the locally refreshed OpenAI model pricing snapshot; it is not authoritative billing. The committed data omits local session-log paths.</p>
    <p>Sources: <a href="https://programbench.com/extended/">ProgramBench extended results</a>, <a href="https://programbench.com/run/gpt-5-5-xhigh/">GPT 5.5 xhigh run detail</a>, and this repository's generated CSV summaries.</p>
  </main>
</body>
</html>
"""


def build(args: argparse.Namespace) -> None:
    rows = [row for path in args.results_csv for row in read_results(Path(path).expanduser())]
    output_dir = Path(args.output_dir).expanduser()
    target_ids = read_target_ids(Path(args.target_set).expanduser())
    official_tasks = load_task_baselines(output_dir)
    if args.clean_output:
        for generated in (output_dir / "run", output_dir / "task", output_dir / "official-run"):
            if generated.exists():
                shutil.rmtree(generated)
        for generated in (
            output_dir / "data" / "results.json",
            output_dir / "data" / "results.csv",
            output_dir / "data" / "programbench-run-baselines.json",
        ):
            if generated.exists():
                generated.unlink()
    if args.refresh_baselines:
        refresh_baselines(output_dir)
    repeated = repeatability_groups(rows)
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_instances": len(rows),
        "programbench_tasks": PROGRAMBENCH_TASKS,
        "groups": result_groups(rows),
        "tasks": task_groups(rows, target_ids, official_tasks),
        "repeatability": repeated,
        "repeatability_summary": repeatability_summary(repeated),
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
    for task in data["tasks"]:
        task_dir = output_dir / "task" / str(task["instance_id"])
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "index.html").write_text(render_task_detail(str(task["instance_id"]), rows, official_tasks))
    print(output_dir / "index.html")
    print(output_dir / "data" / "results.json")
    print(output_dir / "data" / "results.csv")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static ProgramBench /goal report site")
    parser.add_argument("results_csv", nargs="*")
    parser.add_argument("--output-dir", default="docs")
    parser.add_argument("--target-set", default="target_sets/all_tasks.txt")
    parser.add_argument("--clean-output", action="store_true")
    parser.add_argument(
        "--refresh-baselines",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fetch latest ProgramBench public baseline rows before rendering.",
    )
    build(parser.parse_args())


if __name__ == "__main__":
    main()
