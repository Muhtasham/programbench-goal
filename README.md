# GoalBench

Codex `/goal` benchmark runner for ProgramBench tasks.

This repo runs GPT-5.5 Codex CLI goal mode against ProgramBench task images,
packages the generated code as `submission.tar.gz`, evaluates with
ProgramBench's own evaluator, and builds a ProgramBench-style public report.

This is not the official mini-SWE-agent baseline. Results should be labeled as
Codex `/goal` scaffold results.

## Start Here

The primary public run is:

- `gpt-5.5`
- reasoning effort `xhigh`
- Codex `/goal`
- `no-internet` mode
- Linux `amd64`
- ProgramBench's 200 task set

That mode keeps the target container offline, blocks source/package lookup, and
keeps target probing black-box. It is not a mini-SWE-agent reproduction, but it
is the cleanest GoalBench measurement of GPT-5.5 with Codex `/goal` on
ProgramBench.

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

## Run Lifecycle

The runner separates inference, packaging, evaluation, and publishing. Codex is
only active during inference; ProgramBench scoring happens afterward.

```text
1. Prepare task
   programbench_goal_runner.py prepare <instance>
     ├─ create per-task run directory
     ├─ write GOAL_PROMPT.md and GOAL_OBJECTIVE.txt
     ├─ create solution/ as the only useful Codex workspace
     ├─ create guard-bin/ wrappers for blocked tools
     ├─ create start-target.sh, start-codex-goal.sh, package-submission.sh
     └─ record run.json metadata

2. Start black-box target
   start-target.sh
     └─ docker run programbench/<instance> with source removed

3. Start Codex /goal
   start-codex-goal.sh
     ├─ trust only solution/ in Codex config
     ├─ tmux new-session -c solution/
     ├─ codex --enable goals --disable plugins --disable apps \
     │       -m gpt-5.5 -c model_reasoning_effort=<high|xhigh> \
     │       -C solution/ --yolo --no-alt-screen
     ├─ send "/goal <objective>"
     └─ paste GOAL_PROMPT.md

4. Package submission
   package-submission.sh
     └─ tar solution/ into submission.tar.gz

5. Evaluate
   eval-submission.sh ../ProgramBench
     └─ ProgramBench evaluates submission.tar.gz with its Docker evaluator

6. Publish
   build-report.py + privacy-scan.py
     └─ publish sanitized metrics/evidence only
```

### Strict Egress

No-internet-style modes run Codex as a dedicated non-root user, then apply a
UID-scoped Linux egress guard to that user. Root/coordinator still needs normal
network access for setup, Git, Docker, and publishing; the Codex task user does
not.

```text
root / coordinator user
  ├─ starts tmux and Docker target containers
  ├─ can pull repo updates and publish GitHub Pages
  └─ runs ProgramBench evaluation

codex_user
  ├─ runs Codex CLI inside solution/
  ├─ sees guard-bin/ first on PATH
  ├─ can connect to OpenAI/Codex endpoints for model calls
  └─ cannot fetch GitHub/source/package/internet content

iptables owner rules
  ├─ match only codex_user UID
  ├─ allow loopback
  ├─ allow DNS needed for the allowlist mode
  ├─ allow HTTPS to resolved OpenAI/Codex allowlist IPs
  └─ reject the rest
```

The stricter proxy mode narrows this further: `codex_user` can only reach a
local loopback proxy, and that proxy is responsible for OpenAI/Codex outbound
traffic. In both modes, benchmark enforcement also happens above the network
layer through `guard-bin/`, target wrapper commands, and the post-run audit.

### Sharded Evaluation

ProgramBench evaluation is usually slower than Codex inference, so full runs can
ship completed submissions to eval-only machines. Workers never publish.

```text
goalbench-coordinator-1
  ├─ owns Codex credentials
  ├─ runs all /goal inference
  ├─ writes local_state/ and ~/pb-goal-runs/
  ├─ creates shard files after inference
  ├─ may evaluate shard 0, if needed
  ├─ rsyncs worker eval outputs back
  └─ publishes the final site once

goalbench-eval-1..N
  ├─ receive copied run artifacts
  ├─ run start-eval-shard-tmux.sh for assigned instances
  ├─ run ProgramBench evaluator sequentially
  └─ do not run Codex inference or publish
```

## Quick Setup

Use a Linux `amd64` VM for serious runs. ProgramBench publishes task images for
`linux/amd64`; Mac/ARM runs are only smoke tests.

```bash
git clone git@github.com:Muhtasham/goalbench.git
cd goalbench
scripts/bootstrap-linux-vm.sh
codex login
scripts/doctor.sh configs/linux-smoke-nointernet-xhigh.json
```

The bootstrap installs Docker, `uv`, `tmux`, Codex CLI if missing, a sibling
`../ProgramBench` checkout, and the narrow target wrapper used by clean
no-internet runs.

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
| `no-internet` | `configs/full-nointernet-xhigh.json` | Primary Codex `/goal` scaffold. Internet/source/package lookup is blocked, target binary-analysis tools are blocked, and target probing stays black-box. |
| `no-internet-local-tools` | `configs/full-localtools-xhigh.json` | Coming soon. Non-compliant local-tools ablation: internet/source/package lookup remains blocked, but local binary-analysis/tracing tools are allowed. |

Any mode with `no-internet` semantics must use strict host egress. The runner
refuses those configs unless `strict_egress=true`, and the launch doctor
requires a dedicated non-root `codex_user` with the OpenAI-only egress guard
active. The coordinator may run as root for Docker/eval access, but the
generated Codex `/goal` tmux sessions run as that dedicated user.

Recommended run order:

On a larger Linux host, use the `full-*` configs. On the current Hetzner
`cpx62` runner, use the matching `cpx62-*` configs; they disclose
`16 CPU / 30g`.

1. `cpx62-nointernet-xhigh`
2. `cpx62-nointernet-high`
3. `cpx62-localtools-xhigh` (coming soon)

Run `high` after the xhigh primary run when you want a direct reasoning-effort
comparison on the same VM/scaffold.

## Eval Fleet

For full 200-task runs, inference usually finishes before ProgramBench
evaluation. Keep one coordinator/publisher and use eval-only workers for
shards. Refer to machines by stable role labels; keep provider IPs and SSH
targets in local operator notes only.

| Label | Role | Shard | Publishes |
| --- | --- | ---: | --- |
| `goalbench-coordinator-1` | coordinator + evaluator | 0 | yes |
| `goalbench-eval-1` | eval worker | 1 | no |
| `goalbench-eval-2` | eval worker | 2 | no |
| `goalbench-eval-3` | eval worker | 3 | no |

Current full-run convention:

- tmux session: `goalbench-eval-shard-<shard>-<run-version>`
- node log label: `NODE_LABEL=goalbench-eval-<n>` or
  `NODE_LABEL=goalbench-coordinator-1`
- worker behavior: finalize assigned instances only, never publish
- coordinator behavior: merge worker outputs, rebuild the site, and publish

Start an eval shard on a synced host with:

```bash
RUN_VERSION=<version> NODE_LABEL=goalbench-eval-1 \
  scripts/start-eval-shard-tmux.sh \
  configs/cpx62-nointernet-xhigh.json \
  local_state/batches/cpx62-nointernet-xhigh/<version>/shards/shard-1.txt \
  1
```

Workers should only run shard finalizers and rsync results back. The
coordinator is the only host that rebuilds or publishes the website.

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
- [Public report](https://muhtasham.github.io/goalbench/)
