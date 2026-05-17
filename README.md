# GoalBench

Codex `/goal` runner for ProgramBench tasks.

GoalBench runs Codex CLI goal mode against ProgramBench cleanroom task images,
packages each generated replacement as `submission.tar.gz`, evaluates with
ProgramBench, and publishes a static report.

This is a Codex `/goal` scaffold measurement, not the official ProgramBench
mini-SWE-agent baseline.

## Current Public Track

Primary track:

- model: `gpt-5.5`
- reasoning: `xhigh`
- agent: Codex CLI `/goal`
- mode: `no-internet`
- platform: Linux `amd64`
- task set: ProgramBench 200 tasks

The no-internet track blocks source/package lookup and target binary-analysis
tools. Codex may only probe the target through normal CLI behavior and bundled
documentation inside the cleanroom target container.

## Architecture

```text
laptop
  └─ ssh to Linux amd64 coordinator

coordinator VM
  ├─ tmux Codex /goal sessions, one per active task
  ├─ offline ProgramBench target containers for black-box probing
  ├─ local_state/ for batch state and report inputs
  └─ ~/pb-goal-runs/ for per-task prompts, submissions, eval JSON

eval workers, optional
  ├─ receive copied run artifacts
  ├─ finalize assigned shards with ProgramBench
  └─ never publish
```

Codex runs on the VM host, not inside Docker. Docker is used for target
containers during inference and for ProgramBench evaluation after packaging.

## Setup

Use Linux `amd64` for serious runs. ProgramBench task images are published for
`linux/amd64`; Mac/ARM is smoke-test only.

```bash
git clone git@github.com:Muhtasham/goalbench.git
cd goalbench
scripts/bootstrap-linux-vm.sh
codex login
scripts/doctor.sh configs/linux-smoke-miniswecompat-xhigh.json
```

Bootstrap installs Docker, `uv`, `tmux`, Codex CLI if missing, a sibling
`../ProgramBench` checkout, and the target wrapper used by no-internet runs.

## Smoke Run

```bash
scripts/start-sweep-tmux.sh configs/linux-smoke-miniswecompat-xhigh.json
uv run python scripts/run-config.py status configs/linux-smoke-miniswecompat-xhigh.json
uv run python scripts/run-config.py finalize configs/linux-smoke-miniswecompat-xhigh.json
```

Do not treat smoke scores as ProgramBench-comparable.

## Primary Sweep

```bash
scripts/run-sweep.sh --dry-run
scripts/run-sweep.sh
```

By default, full configs run up to 10 parallel Codex `/goal` sessions. Lower
parallelism on smaller hosts:

```bash
scripts/run-sweep.sh --max-parallel 4
MAX_PARALLEL=4 scripts/start-sweep-tmux.sh configs/full-miniswecompat-xhigh.json
```

Publish only after evaluation artifacts are ready:

```bash
scripts/run-sweep.sh --publish
```

## Modes

| Mode | Config | Meaning |
| --- | --- | --- |
| `no-internet` | `configs/full-nointernet-xhigh.json` | Stricter GoalBench track. Internet/source/package lookup is blocked, target binary-analysis tools are blocked, target probing stays black-box, and the prompt asks for an explicit behavior audit. |
| `mini-swe-compatible-nointernet` | `configs/full-miniswecompat-xhigh.json` | Parity attempt. Same no-internet enforcement, but with a shorter mini-SWE-style task prompt and no GoalBench audit loop requirements. Still a Codex `/goal` scaffold, not an official mini-SWE-agent baseline. |
| `no-internet-local-tools` | `configs/full-localtools-xhigh.json` | Coming soon. External lookup stays blocked, but local binary-analysis/tracing tools are allowed. Non-compliant ablation. |

Current recommended sequence:

1. `cpx62-miniswecompat-xhigh`
2. `cpx62-miniswecompat-high`
3. `cpx62-nointernet-xhigh` if we want the stricter GoalBench audit-heavy scaffold
4. `cpx62-localtools-xhigh` once enabled

## No-Internet Enforcement

No-internet runs use layered controls:

- Codex runs as a dedicated non-root `codex_user`.
- UID-scoped egress rules allow only OpenAI/Codex traffic needed for model calls.
- `guard-bin/` blocks source lookup, package installs, binary-analysis tools,
  and broad host traversal.
- The target is accessed through the wrapper command, not direct Docker root
  access.
- Post-run audits flag parent traversal and other compliance issues.

Root/coordinator still needs normal network for setup, Docker, Git, and
publishing. The restricted Codex task user does not.

## Sharded Evaluation

For full runs, evaluate completed submissions on eval-only workers.

| Label | Role | Publishes |
| --- | --- | --- |
| `goalbench-coordinator-1` | inference, shard 0, merge, publish | yes |
| `goalbench-eval-1` | eval shard 1 | no |
| `goalbench-eval-2` | eval shard 2 | no |
| `goalbench-eval-3` | eval shard 3 | no |

Start a shard on a synced worker:

```bash
RUN_VERSION=<version> NODE_LABEL=goalbench-eval-1 \
  scripts/start-eval-shard-tmux.sh \
  configs/cpx62-miniswecompat-xhigh.json \
  local_state/batches/cpx62-miniswecompat-xhigh/<version>/shards/shard-1.txt \
  1
```

Only the coordinator should rebuild or publish the website.

## Reporting

The static report mirrors ProgramBench's headline shape:

- resolved rate
- almost-resolved rate at `score >= 0.95`
- average behavioral pass rate
- estimated cost
- Codex calls
- wall-clock time
- per-task detail pages

Cost is estimated from local Codex token logs and a refreshed OpenAI pricing
snapshot. It is not authoritative billing.

Build locally:

```bash
uv run python scripts/build-report.py --output-dir docs
uv run python scripts/privacy-scan.py
```

Public output includes sanitized aggregate rows and public evidence summaries.
Raw Codex logs and submission tarballs stay local by default.

## Useful Commands

```bash
scripts/doctor.sh configs/full-miniswecompat-xhigh.json
uv run python scripts/run-config.py status configs/full-miniswecompat-xhigh.json
uv run python scripts/run-config.py finalize configs/full-miniswecompat-xhigh.json
scripts/backup-run-root.sh --batch-name full-miniswecompat-xhigh --run-version <version>
uv run ruff check .
uv run ty check
uv run pre-commit run --all-files
```

## Links

- [Public report](https://muhtasham.github.io/goalbench/)
- [Detailed runbook](docs/runbook.md)
- [ProgramBench](https://programbench.com/)
