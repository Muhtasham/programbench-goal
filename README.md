# ProgramBench Goal

Codex `/goal` runner for ProgramBench tasks.

This repo runs GPT-5.5 Codex CLI goal mode against ProgramBench cleanroom task
images, packages the generated code as `submission.tar.gz`, evaluates with
ProgramBench's own evaluator, and builds a ProgramBench-style public report.

This is not the official mini-SWE-agent baseline. Results should be labeled as
Codex `/goal` scaffold results.

## Start Here

For the Noam/Jake question, the primary run is:

- `gpt-5.5`
- reasoning effort `xhigh`
- Codex `/goal`
- `no-internet` mode
- Linux `amd64`
- ProgramBench's 200 task set

That mode keeps the target container offline, blocks source/package lookup, and
keeps target probing black-box. It is not a mini-SWE-agent reproduction, but it
is the cleanest answer to “what happens if GPT-5.5 gets `/goal` and more wall
clock time on ProgramBench?”

## How It Runs

Codex runs on the Linux VM host, not inside Docker. Docker is used for the
black-box target containers during inference and for ProgramBench evaluation
after a submission is packaged.

```text
Your laptop
  └─ ssh into Linux amd64 VM

Linux VM
  ├─ tmux: one Codex CLI /goal session per active task
  │    └─ writes only that task's solution/ directory
  ├─ Docker: one offline ProgramBench target container per active task
  │    └─ exposes /workspace/executable for black-box probing
  ├─ local_state/: batch state, summaries, public report inputs
  └─ ~/pb-goal-runs/: per-task prompts, logs, submissions, eval JSON

Later, during evaluation
  └─ ProgramBench runs submission.tar.gz through its Docker evaluator
```

Each task has its own `solution/`, `guard-bin/`, `tool-caches/`, target
container, tmux transcript, and `submission.tar.gz`. `max_parallel` controls
how many Codex task sessions are active at once; evaluation is run
sequentially by default for cleaner results.

## Quick Setup

Use a Linux `amd64` VM for serious runs. ProgramBench publishes task images for
`linux/amd64`; Mac/ARM runs are only smoke tests.

```bash
git clone git@github.com:Muhtasham/programbench-goal.git
cd programbench-goal
scripts/bootstrap-linux-vm.sh
codex login
scripts/doctor.sh configs/linux-smoke-nointernet-xhigh.json
```

The bootstrap installs Docker, `uv`, `tmux`, Codex CLI if missing, a sibling
`../ProgramBench` checkout, and the narrow target wrapper used by paper-style
runs.

## Smoke Run

Start with a small Linux smoke:

```bash
scripts/start-sweep-tmux.sh configs/linux-smoke-nointernet-xhigh.json
uv run python scripts/run-config.py status configs/linux-smoke-nointernet-xhigh.json
```

When it finishes, finalize/evaluate:

```bash
uv run python scripts/run-config.py finalize configs/linux-smoke-nointernet-xhigh.json
```

Do not treat Mac/ARM or small-VM smoke scores as ProgramBench-comparable.

## Full Run

Default full sweep:

```bash
scripts/run-sweep.sh --dry-run
scripts/run-sweep.sh
```

Full-run configs default to `max_parallel=10`, so a normal launch can run up to
ten Codex `/goal` task sessions at once. Lower it on smaller VMs with either:

```bash
scripts/run-sweep.sh --max-parallel 4
MAX_PARALLEL=4 scripts/start-sweep-tmux.sh configs/full-nointernet-xhigh.json
```

Publish the regenerated GitHub Pages report after evaluation:

```bash
scripts/run-sweep.sh --publish
```

For long runs, use incremental finalize/reporting so completed tasks are scored
without waiting for all 200 instances:

```bash
scripts/run-sweep.sh --incremental-finalize --publish
```

`scripts/run-sweep.sh` uses `PROGRAMBENCH_REPO` if set, otherwise it
auto-detects a sibling `../ProgramBench` checkout. Run
`scripts/bootstrap-programbench.sh` if that checkout does not exist.

## Modes

Use separate batches for each mode. Do not mix them in one result.

| Mode | Config | Meaning |
| --- | --- | --- |
| `no-internet` | `configs/full-nointernet-xhigh.json` | Primary Codex `/goal` scaffold. No external lookup, black-box target probing. |
| `paper` | `configs/full-paper-xhigh.json` | Stricter ProgramBench-style cleanroom mode for Codex `/goal`; not official mini-SWE-agent. |
| `no-internet-local-tools` | `configs/full-localtools-xhigh.json` | Non-compliant tool-starvation ablation. No internet/source lookup, but local binary-analysis/tracing tools are allowed. |
| `open-internet` | `configs/full-open-xhigh.json` | Non-compliant ceiling run with normal Codex internet/package access. |

Recommended run order:

On a paper-sized Linux host, use the `full-*` configs. On the current Hetzner
`cpx62` runner, use the matching `cpx62-*` configs; they disclose
`16 CPU / 30g` instead of `20 CPU / 60g`.

1. `cpx62-nointernet-xhigh`
2. `cpx62-nointernet-high`
3. `cpx62-paper-xhigh`
4. `cpx62-localtools-xhigh`
5. `cpx62-open-xhigh`

Run `high` after the xhigh primary run when you want a direct reasoning-effort
comparison on the same VM/scaffold.

## Reporting

The report mirrors ProgramBench's public shape:

- resolved rate
- almost-resolved rate at `score >= 0.95`
- average behavioral pass rate
- estimated cost
- Codex calls
- wall-clock time
- per-task detail pages

Cost is an estimate from local Codex token logs and the refreshed OpenAI pricing
snapshot. It is not authoritative billing.

Build the site manually:

```bash
uv run python scripts/build-report.py --output-dir docs
uv run python scripts/privacy-scan.py
```

The public site publishes sanitized aggregate rows, public evidence summaries,
and downloadable CSV/JSON. Raw Codex logs and submission tarballs stay local by
default.

## Useful Commands

```bash
# Check prerequisites and config
scripts/doctor.sh configs/full-nointernet-xhigh.json

# Watch batch status
uv run python scripts/run-config.py status configs/full-nointernet-xhigh.json

# Rebuild report from current local state
uv run python scripts/run-config.py finalize configs/full-nointernet-xhigh.json

# Backup a VM run before teardown
scripts/backup-run-root.sh --batch-name full-nointernet-xhigh --run-version <version>

# Run local quality checks
uv run ruff check .
uv run ty check
uv run pre-commit run --all-files
```

## More Docs

- [Detailed runbook](docs/runbook.md)
- [Paper/compliance notes](docs/paper-compliance.md)
- [Public report](https://muhtasham.github.io/programbench-goal/)
