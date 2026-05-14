# ProgramBench Goal

Small harness for running Codex GPT-5.5 `/goal` against ProgramBench tasks.

This is a Codex `/goal` scaffold, not the official mini-SWE-agent baseline
scaffold. It uses ProgramBench's Docker task images and evaluation code, but the
inference loop is Codex CLI goal mode. Report results as Codex `/goal` results,
not as mini-SWE-agent results.

The harness keeps the solving workspace separate from the ProgramBench evaluator
repo. It gives Codex a clean writable solution directory and produces the
`submission.tar.gz` layout that `programbench eval` expects. The default mode is
the no-internet Codex `/goal` harness; use `--inference-mode paper` for the
closest ProgramBench-cleanroom run and `--inference-mode open-internet` only for
the explicitly non-compliant open-web ablation.

ProgramBench is a free-form reimplementation benchmark. The agent should choose
the language, architecture, source layout, abstractions, and build script from
black-box observations of the executable plus documentation already present in
the cleanroom container. It should not receive method signatures, skeletons,
product requirements, hidden hints, or task-specific harness tuning.

If ProgramBench publishes the exact mini-SWE-agent baseline prompt, use it via
`--prompt-template` and keep only the local runtime substitutions needed for the
container name and solution path. The ProgramBench usage guide says their paper
baselines used mini-SWE-agent with a framework similar to mini-SWE-agent's
SWE-bench runner and that they expect to release that baseline system in
mini-SWE-agent. Until that exists in public code, keep this runner labeled as a
separate Codex `/goal` scaffold.

## Requirements

- Linux `amd64` host for real runs.
- `uv`.
- Docker.
- Codex CLI with `/goal` support.
- `tmux`.
- A separate ProgramBench checkout only for evaluation.

For a fresh clone of this repo, bootstrap the ProgramBench evaluator as a
sibling checkout:

```bash
scripts/bootstrap-programbench.sh
scripts/install-target-wrapper.sh
```

The bootstrap script clones or updates `../ProgramBench` and runs
`uv sync --project` there. The wrapper installer grants the current user
passwordless sudo for `/usr/local/bin/pb-target-exec` only, so Codex can probe
target containers without direct Docker socket access. `scripts/run-sweep.sh`
auto-detects the sibling ProgramBench checkout. If you keep ProgramBench
somewhere else, set `PROGRAMBENCH_REPO=/path/to/ProgramBench` or pass
`--programbench-repo /path/to/ProgramBench`.

The ProgramBench images are published for `linux/amd64`. Docker Desktop on Apple
Silicon can sometimes emulate them, but serious runs should happen on Linux
`amd64`.

## Fresh Linux VM Setup

Use a real Ubuntu `amd64` VM for Noam-facing results. Recommended minimum:
20 vCPU, 60GB RAM, and enough disk for Docker images/eval artifacts; 32 vCPU,
96-128GB RAM, and 500GB disk leaves more room.

On the VM:

```bash
git clone git@github.com:Muhtasham/programbench-goal.git
cd programbench-goal
scripts/bootstrap-linux-vm.sh
```

The bootstrap installs base packages, Docker, `uv`, `tmux`, Codex CLI when
missing, the sibling `../ProgramBench` checkout, and the narrow
`/usr/local/bin/pb-target-exec` wrapper. It also writes a Codex config with
`service_tier = "fast"` and `[features].fast_mode = true`, so GPT-5.5 runs use
Codex fast mode by default. Fast mode trades higher credit consumption for
lower latency; API-key logins use standard API pricing instead. The bootstrap
also trusts the VM run directories and sets managed defaults for YOLO-style
`approval_policy = "never"` and `sandbox_mode = "danger-full-access"`. If it
adds your user to the Docker group, log out and back in before running sweeps.

Then authenticate Codex on the VM:

```bash
codex login
docker run --rm hello-world
scripts/doctor.sh configs/linux-smoke-nointernet-xhigh.json
```

For Codex app remote connections, add the VM to your local `~/.ssh/config`,
confirm `ssh <alias>` works, enable `remote_connections = true` in local Codex
config if needed, then open this repo as a remote project.

Run the Linux smoke first:

```bash
scripts/start-sweep-tmux.sh configs/linux-smoke-nointernet-xhigh.json
uv run python scripts/run-config.py status configs/linux-smoke-nointernet-xhigh.json
tail -f local_state/logs/pb-goal-linux-smoke-nointernet-xhigh.log
```

For smoke-only debugging, set `ALLOW_PARTIAL=1` if you want the report to
rebuild before every target finishes. Do not use that for a public full run.

For the stricter paper-mode smoke:

```bash
scripts/start-sweep-tmux.sh configs/linux-smoke-paper-xhigh.json
```

If you are using a smaller Hetzner shared `cpx62` smoke VM, use the labeled
16 CPU / 30GB config instead:

```bash
scripts/doctor.sh configs/hetzner-cpx62-smoke-xhigh.json
scripts/start-sweep-tmux.sh configs/hetzner-cpx62-smoke-xhigh.json
```

Only start full sweeps after a Linux smoke produces `submission.tar.gz`,
ProgramBench `.eval.json`, `results.csv`, and a clean audit.

## Isolation Model

In `paper`, `no-internet`, and `no-internet-local-tools` modes, the target
binary runs in a Docker container with `--network none`, so probes against the
original program cannot reach the internet. The `paper` and `no-internet`
prompts require probing through `docker exec -u agent ...`; this matters because
the cleanroom executable is execute-only for the `agent` user, while root can
bypass file permissions. The `no-internet-local-tools` mode intentionally allows
root-level target inspection as a non-compliant ablation.

Codex itself runs on the host because it must reach OpenAI. The `paper` and
`no-internet` prompts forbid internet use, package managers, upstream source
lookup, decompilers, the ProgramBench evaluator repository, and external
replacement docs for images with missing documentation. The launcher does not
enable web search. If you need hard enforcement for host shell commands too, run
this harness inside a VM or host environment with an egress policy that only
permits Codex/OpenAI traffic.

For stricter cleanroom runs, avoid giving the Codex user direct Docker socket
access. Install the narrow target wrapper and prepare `paper` runs with
`--target-access wrapper`:

```bash
scripts/install-target-wrapper.sh
uv run python programbench_goal_runner.py prepare jqlang__jq.b33a763 \
  --inference-mode paper \
  --target-access wrapper
```

In wrapper mode the prompt tells Codex to probe targets through:

```bash
sudo -n /usr/local/bin/pb-target-exec <container> bash -lc '<command>'
```

That wrapper only performs `docker exec -u agent` against `pb-goal-*`
containers and refuses nested Docker commands. For a publishable Linux run,
grant the dedicated Codex user only that wrapper through sudoers instead of
adding it to the `docker` group.

The Codex launcher uses YOLO mode. Generated launch scripts prefer `--yolo`
when the installed Codex accepts it, then fall back to the public long flag
`--dangerously-bypass-approvals-and-sandbox`:

```bash
codex --enable goals --disable plugins --disable apps \
  -m gpt-5.5 -c model_reasoning_effort='xhigh' \
  --yolo --no-alt-screen
```

Each generated script also marks its exact solution directory trusted in the
local Codex config before launch, so unattended `tmux` runs do not stop at the
directory trust prompt.

Override `--model` and `--reasoning-effort` when preparing runs if you want a
separate high/xhigh sweep. These values are written into `run.json` and the
metrics CSV. Container and `tmux` session names include the run name, so high
and xhigh runs for the same instance can coexist. Default run names include the
inference mode plus non-default model or effort values.

The generated target container defaults to the paper's resource setting of 20
CPUs and 60GB RAM. For local smoke tests on smaller machines, pass
`--docker-cpus` and `--docker-memory` to `prepare` or `prepare-batch`; do not
report those local smoke runs as paper-comparable results.

For `paper` and `no-internet`, the generated Codex launcher prepends a
`guard-bin` directory to `PATH`. It blocks common host-side internet,
source/package lookup, and binary-analysis commands, restricts `docker` to the
allowed `docker exec -u agent <container> ...` target-probing form, and points
common tool caches at an empty per-run directory. Local build commands such as
`go build` and `cargo build` are still allowed; source-acquisition commands such
as `go get`, `cargo install`, and `pip install` are blocked. Agent-created
black-box probes, fuzzers, generators, and comparison scripts are allowed when
they interact with the target only through normal runtime behavior. This catches
common mistakes. It also blocks common local file-inspection commands from
reading parent directories, the run root, home paths, or the evaluator checkout.
Packaging is exposed as a `package-submission` command in `guard-bin`, so Codex
does not need to invoke or inspect parent-directory helper scripts.
This is still not a replacement for a VM/container/user-level egress policy.

See `docs/paper-compliance.md` for the paper/FAQ compliance matrix.

## Inference Modes

Default mode is `no-internet`, the recommended Codex `/goal` scaffold for the
Noam/Jake question. It keeps the target container offline and keeps the
host-side internet/package/source guards enabled, but it is reported separately
from `paper` so we can measure the Codex scaffold without claiming
mini-SWE-agent parity:

```bash
uv run python programbench_goal_runner.py prepare jqlang__jq.b33a763
```

For ProgramBench-style cleanroom reporting, opt into `paper`:

```bash
uv run python programbench_goal_runner.py prepare jqlang__jq.b33a763 \
  --inference-mode paper
```

The explicit no-internet form is equivalent to the default:

```bash
uv run python programbench_goal_runner.py prepare jqlang__jq.b33a763 \
  --inference-mode no-internet
```

There is a second no-internet ablation for the “tool-starved benchmark”
criticism:

```bash
uv run python programbench_goal_runner.py prepare jqlang__jq.b33a763 \
  --inference-mode no-internet-local-tools
```

This keeps external internet/source/package lookup blocked and keeps the target
container on `--network none`, but it allows local installed tools, local
binary-analysis/tracing tools, and root-level target inspection through the
target container. This is intentionally non-compliant with ProgramBench
cleanroom rules and must be reported separately.

Run `open-internet` only as a separate, explicitly non-compliant full Codex
harness ablation:

```bash
uv run python programbench_goal_runner.py prepare jqlang__jq.b33a763 \
  --inference-mode open-internet
```

No-internet, no-internet-local-tools, and open-internet runs still produce
`submission.tar.gz` and can be evaluated with ProgramBench, but report them
separately as Codex `/goal` experiments. Do not mix them with cleanroom
ProgramBench results.

## Reporting

Use ProgramBench's resolved, almost-resolved, average pass-rate, cost, and calls
shape so results are comparable to the leaderboard. Scores are computed through
ProgramBench's own `EvaluationResult` and `InstanceEvalSummary` logic after the
same active-branch and ignored-test filtering used by `programbench info`.
Resolved means the filtered behavioral test pass rate is exactly `1.0`; warning
and evaluator-problem fields are disclosed separately. Label our cost column as
estimated cost: Codex session logs expose token counts and call counts, but not
authoritative billed dollars. Label the scaffold explicitly, for example:
`GPT-5.5 xhigh / Codex goal`, and disclose wall-clock time, inference mode,
host/network enforcement, and any paper deviations. Treat this as a scaffold
comparison against mini-SWE-agent, not an apples-to-apples model-only
comparison.

Cost uses local Codex `token_count` events from both `~/.codex/sessions` and
`~/.codex/archived_sessions`. The estimate prices uncached input, cached input,
and output tokens. `reasoning_output_tokens` is kept in the audit file but is
not added again because it is a subset of output tokens in the local logs. When
OpenAI's model docs expose a long-context threshold, the summarizer applies
that multiplier per Codex call using `last_token_usage.input_tokens`.

## Optional Host Egress Guard

For a stronger run on Linux, create a dedicated user for the Codex process and
apply the UID-scoped OpenAI egress guard:

```bash
sudo useradd -m codex-runner
sudo scripts/linux-openai-egress-guard.sh apply codex-runner
sudo scripts/linux-openai-egress-guard.sh status codex-runner
```

By default the guard allows DNS plus HTTPS to the currently resolved IPs for:

```text
api.openai.com auth.openai.com chatgpt.com ab.chatgpt.com persistent.oaistatic.com
```

This is intentionally simple and conservative. It is IP-based because Linux
firewalls do not filter by domain name directly; if OpenAI/CDN IPs change during
a long run, refresh the rules by running `apply` again. To remove the guard:

```bash
sudo scripts/linux-openai-egress-guard.sh delete codex-runner
```

For strict compliance, do not give the Codex user broad Docker socket access.
Raw Docker access is effectively root-equivalent and can bypass network
controls. The `paper` and `no-internet` prompts require
`docker exec -u agent ...`, but for a publishable run you should either
supervise that boundary or expose only a narrow wrapper for target execution.

## Metrics

Use ProgramBench's primary metric when reporting results: fully resolved
instances. Almost-resolved and average pass rate are useful diagnostics, but
they should not be the headline score.

Metric formulas:

- `resolved_rate = count(score == 1.0) / evaluated_instances`
- `almost_resolved_rate = count(score >= 0.95) / evaluated_instances`
- `total_cost_usd = sum(estimated_cost_usd per instance)`
- `total_calls = sum(calls per instance)`
- `average_cost_usd = total_cost_usd / evaluated_instances`
- `average_calls = total_calls / evaluated_instances`

ProgramBench run-detail pages display total cost and total calls. ProgramBench's
extended leaderboard table displays average cost and average calls per instance.
The generated report follows the same split.

## Doctor

Before launching any expensive run, use the doctor script:

```bash
scripts/doctor.sh configs/linux-smoke-nointernet-xhigh.json
```

It checks the selected config, required commands, host architecture, Docker
daemon/resources against the config, ProgramBench checkout, wrapper access,
target set, and Codex version. `scripts/start-sweep-tmux.sh` runs the same
check before launching unless `SKIP_DOCTOR=1` is set.

Before a serious run, check metric parity against ProgramBench's scoring code
and bundled fixture runs:

```bash
uv run --project /path/to/ProgramBench python scripts/check-metric-parity.py \
  --programbench-repo /path/to/ProgramBench
```

`scripts/run-sweep.sh` runs this check automatically whenever a ProgramBench
checkout is supplied.

Local state lives under `local_state/`, which is ignored by git. Use it for
pricing snapshots, run manifests, copied Codex logs, eval JSON, result CSVs, and
trace bundles that should be shareable locally but not committed.

Refresh OpenAI pricing before summarizing cost:

```bash
uv run python scripts/refresh-openai-pricing.py
```

This writes `local_state/openai_pricing.json` from official OpenAI model docs.
OpenAI does not currently expose a supported structured pricing endpoint for
these model price cards, so this repository stores an official-doc snapshot
instead. The sweep script refreshes it before scoring. Offline rebuilds keep
using the cached snapshot and `usage-audit.json` will flag it if it is stale.
The summarizer reads that file by default; `CODEX_INPUT_USD_PER_MTOK`,
`CODEX_CACHED_INPUT_USD_PER_MTOK`, and `CODEX_OUTPUT_USD_PER_MTOK` still
override it when set.

Evaluation may need internet access to fetch ProgramBench test blobs from
Hugging Face. That is evaluator-side access, not inference-side access. For
repeatable runs, prefetch the blobs from the ProgramBench checkout before
evaluating:

```bash
uv run --project /path/to/ProgramBench programbench blob sync <instance_id>
```

## Quickstart

Prepare a `jq` run:

```bash
uv run python programbench_goal_runner.py prepare jqlang__jq.b33a763
```

Prepare a high-effort comparison run:

```bash
uv run python programbench_goal_runner.py prepare jqlang__jq.b33a763 \
  --reasoning-effort high
```

## Full 200-Task Runs

Do not start all 200 tasks from a laptop as the first serious run. Use the
config runner so the command, mode, resource settings, and batch name are
reproducible. Refresh the official 200-task target set from a ProgramBench
checkout:

```bash
uv run python scripts/write-target-set.py /path/to/ProgramBench \
  --output target_sets/all_tasks.txt
uv run python scripts/validate-target-set.py target_sets/all_tasks.txt \
  --programbench-repo /path/to/ProgramBench
```

The validator expects 200 real tasks by default: all ProgramBench task metadata
entries except the bundled `testorg__` fixture. `scripts/run-sweep.sh` runs this
validation automatically whenever the config uses `target_sets/all_tasks.txt`.

For the Noam/Jake question, the cleanest primary answer is the no-internet
Codex `/goal` scaffold: same task set, longer/autonomous Codex goal loop, and no
external lookup. It is not the official mini-SWE-agent baseline, but it avoids
the biggest confound from normal Codex internet access:

```bash
scripts/run-sweep.sh --dry-run
scripts/run-sweep.sh
```

By default, `run-sweep.sh` uses `PROGRAMBENCH_REPO` if set, otherwise it
auto-detects a sibling `../ProgramBench` checkout. Run
`scripts/bootstrap-programbench.sh` first if that checkout does not exist yet.

The script refreshes `target_sets/all_tasks.txt`, runs the configured batch,
refreshes the OpenAI pricing snapshot before scoring, finalizes completed
instances, exports sanitized evidence, rebuilds `docs/`, refreshes public
ProgramBench leaderboard rows and per-task baseline context, checks report size,
and runs the privacy scan. By default this updates the local `docs/` site only.
Add `--publish` to commit and push `docs/` to GitHub Pages after the site
rebuild:

```bash
scripts/run-sweep.sh --publish
scripts/run-sweep.sh --skip-watch --publish
```

The tmux helper uses the same defaults without publishing:

```bash
scripts/start-sweep-tmux.sh configs/nointernet-xhigh.json
PUBLISH=1 scripts/start-sweep-tmux.sh configs/nointernet-xhigh.json
```

Use `--offline-report` only when you intentionally want cached pricing and
cached ProgramBench baseline rows for a reproducible or offline rebuild.

The equivalent lower-level commands are:

```bash
uv run python scripts/run-config.py watch configs/full-nointernet-xhigh.json --dry-run
uv run python scripts/run-config.py watch configs/full-nointernet-xhigh.json
```

Run the matching high-effort sweep as a separate batch:

```bash
uv run python scripts/run-config.py watch configs/full-nointernet-high.json
```

For local Mac/ARM harness smoke testing, use the small non-comparable batch
instead of the full 200-task config:

```bash
scripts/run-sweep.sh --config configs/local-mac-smoke-xhigh.json --dry-run
scripts/run-sweep.sh --config configs/local-mac-smoke-xhigh.json
```

This uses five near-miss tasks, `direct-docker`, 8 CPUs, and 8GB RAM. Treat it
as harness validation only; the publishable all-task run should still happen on
Linux amd64.

Check status:

```bash
uv run python scripts/run-config.py status configs/full-nointernet-xhigh.json
```

Finalize completed instances, run ProgramBench evaluation, summarize metrics,
and collect local evidence:

```bash
uv run python scripts/run-config.py finalize configs/full-nointernet-xhigh.json \
  --programbench-repo /path/to/ProgramBench
```

That run is labeled `no-internet`: it blocks external lookup and target binary
analysis, but still discloses that the scaffold is Codex `/goal`, not
mini-SWE-agent.

Run `open-internet` only as a separate ceiling experiment:

```bash
uv run python scripts/run-config.py watch configs/full-open-xhigh.json
```

Open-internet runs are intentionally non-compliant with ProgramBench cleanroom
rules. They answer “how far does the full Codex harness get if normal external
resources are allowed?” rather than “what is the official ProgramBench score?”

For the banteg-style “tool-starved” criticism, run the no-internet local-tools
ablation separately:

```bash
uv run python scripts/run-config.py watch configs/full-localtools-xhigh.json
```

For the closest ProgramBench-cleanroom run, use a Linux `amd64` host with the
wrapper boundary and preflight first:

```bash
uv run python scripts/preflight-paper-host.py \
  --codex-user codex-runner \
  --check-egress-guard \
  --instance-dir /path/to/prepared/paper/instance

uv run python scripts/run-config.py watch configs/full-paper-xhigh.json
```

The committed full-run configs all use `gpt-5.5`, 20 CPUs, 60GB RAM, and
`max_parallel=1`. There are separate `high` and `xhigh` configs for
`no-internet`, `open-internet`, `no-internet-local-tools`, and `paper`. Increase
parallelism only after confirming Codex rate limits and host capacity. Do not
mix reasoning modes in one batch.

Prepare with an official prompt template when one is available:

```bash
uv run python programbench_goal_runner.py prepare jqlang__jq.b33a763 \
  --prompt-template /path/to/official-programbench-prompt.md
```

The generated `run.json` records the prompt template path, template SHA-256,
and rendered prompt SHA-256. If ProgramBench publishes an official baseline
prompt, pin that file and report its hash with the run.

Prepare the near-miss first batch:

```bash
uv run python programbench_goal_runner.py prepare-batch target_sets/first_batch_near_miss.txt \
  --inference-mode no-internet
```

Prepare the same batch with wrapper-mode target access:

```bash
uv run python programbench_goal_runner.py prepare-batch target_sets/first_batch_near_miss.txt \
  --inference-mode paper \
  --target-access wrapper
```

For real sweeps, prefer the resumable batch manager so the laptop does not start
too many Codex `/goal` sessions at once:

```bash
uv run python scripts/run-batch.py watch target_sets/first_batch_near_miss.txt \
  --batch-name first-near-miss-xhigh \
  --max-parallel 1 \
  --inference-mode no-internet \
  --reasoning-effort xhigh
```

Use `--max-parallel 1` on a laptop until we know the active Codex rate limits.
Use separate batch names for `high`, `xhigh`, `paper`, `no-internet`,
`no-internet-local-tools`, and `open-internet` runs. The manager stores resumable state under `local_state/batches/`, starts
new work only when active sessions are below the concurrency cap, and pauses new
launches when a running pane shows rate-limit text.

Check progress:

```bash
uv run python scripts/run-batch.py status --batch-name first-near-miss-xhigh
```

After sessions reach `goal_done`, package, audit, evaluate, summarize, and
collect local artifacts:

```bash
uv run python scripts/run-batch.py finalize \
  --batch-name first-near-miss-xhigh \
  --programbench-repo /path/to/ProgramBench
```

Start the target container:

```bash
~/pb-goal-runs/gpt55-goal-open-jq/jqlang__jq.b33a763/start-target.sh
```

Check the compliance-critical container properties:

```bash
~/pb-goal-runs/gpt55-goal-open-jq/jqlang__jq.b33a763/check-compliance.sh
```

Before running expensive inference, do a full evaluator preflight with a known
bad stub on one small real task. The expected result is a clean evaluation with a
low score, not a solved task. This verifies Docker image access, blob access,
`submission.tar.gz` layout, eval JSON output, and the metrics summarizer.

For a paper-comparable host, run the strict preflight before launching a batch:

```bash
uv run python scripts/preflight-paper-host.py \
  --codex-user codex-runner \
  --check-egress-guard \
  --instance-dir ~/pb-goal-runs/gpt55-goal-paper-jq/jqlang__jq.b33a763
```

The preflight checks Linux `amd64`, Docker CPU/RAM capacity, dedicated-user
existence, direct Docker-group exposure, OpenAI egress guard status, target
container network mode, and generated guard wrappers.

Launch Codex in `tmux` and inject `/goal`:

```bash
~/pb-goal-runs/gpt55-goal-open-jq/jqlang__jq.b33a763/start-codex-goal.sh
```

Attach to the session:

```bash
tmux attach -t pb-goal-gpt55-goal-open-jq-jqlang-jq-b33a763
```

Package the submission:

```bash
~/pb-goal-runs/gpt55-goal-open-jq/jqlang__jq.b33a763/package-submission.sh
```

Inside a Codex task session, use `package-submission` from `guard-bin` instead
of parent-directory paths such as `../package-submission.sh`.

Audit the Codex JSONL trace and package shape before evaluating or reporting:

```bash
uv run python scripts/audit-run.py ~/pb-goal-runs/gpt55-goal-open-jq/jqlang__jq.b33a763
```

Evaluate from a ProgramBench checkout:

```bash
~/pb-goal-runs/gpt55-goal-open-jq/jqlang__jq.b33a763/eval-submission.sh /path/to/ProgramBench
```

Summarize leaderboard-style metrics after evaluation:

```bash
uv run --project /path/to/ProgramBench \
  python /path/to/programbench-goal/scripts/summarize-results.py ~/pb-goal-runs/gpt55-goal-open-jq \
  --programbench-repo /path/to/ProgramBench \
  --output results.csv
```

Run the summarizer in the ProgramBench `uv` environment because it imports
ProgramBench's scoring code. The runner itself stays separate from the evaluator
repo.

The summary reports fully resolved rate, almost-resolved rate (`score >= 0.95`,
matching ProgramBench's displayed leaderboard wording), average pass rate, Codex calls,
wall-clock hours, token usage, and estimated cost. The CSV includes model,
reasoning effort, inference mode, host/resource disclosures, and the exact Codex
JSONL `session_logs` used for each instance, so usage numbers can be audited
directly. Codex CLI session logs expose token counts and call counts, but not
authoritative dollars.

When an output CSV is written, the summarizer also writes `usage-audit.json`
next to it. That file records matched Codex session logs, token totals, pricing
source, pricing snapshot hash, cost estimates, and warnings for missing logs or
pricing. It also records `long_context_calls` when a model's official pricing
docs define a long-context multiplier. The audit includes the pricing snapshot
metadata and a freshness warning when the snapshot is older than 24 hours.

Set these environment variables to estimate cost from current pricing:

```bash
export CODEX_INPUT_USD_PER_MTOK=...
export CODEX_CACHED_INPUT_USD_PER_MTOK=...
export CODEX_OUTPUT_USD_PER_MTOK=...
```

Collect local evidence for a run after evaluation:

```bash
uv run python scripts/collect-run-artifacts.py ~/pb-goal-runs/gpt55-goal-open-jq/jqlang__jq.b33a763
```

The collector writes an ignored bundle under `local_state/run_artifacts/` with a
manifest, `run.json`, eval JSON, `results.csv`, `submission.tar.gz`, package
listing, and copied Codex JSONL logs. This is the local trace bundle to inspect
or selectively share when discussing results. Text artifacts are copied with
local home, run-root, ProgramBench-repo, and Codex-session paths redacted; the
submitted tarball is preserved byte-for-byte.

To audit a row's usage numbers, inspect the `session_logs` path from the CSV:

```bash
python3 - <<'PY' /path/to/codex-session.jsonl
import json, sys
calls = 0
last = None
for line in open(sys.argv[1], errors="replace"):
    event = json.loads(line)
    payload = event.get("payload", {})
    if event.get("type") == "event_msg" and payload.get("type") == "token_count" and payload.get("info"):
        calls += 1
        last = {
            "total_token_usage": payload["info"]["total_token_usage"],
            "last_token_usage": payload["info"].get("last_token_usage"),
        }
print({"calls": calls, **last})
PY
```

## GitHub Pages Report

The public report is generated into `docs/` and deployed by GitHub Actions. Build
it from one or more summarized result CSVs:

```bash
uv run python scripts/build-report.py \
  local_state/open-sample-results.csv \
  local_state/csview-paper-smoke-results.csv \
  --output-dir docs
```

`build-report.py` fetches the latest ProgramBench public baseline rows by
default before rendering. Use `--no-refresh-baselines` only for offline rebuilds.

The report keeps `paper`, `no-internet`, `no-internet-local-tools`, and
`open-internet` tracks separate, includes ProgramBench-style
resolved/almost/average-pass/estimated-cost/calls metrics, and commits only
sanitized aggregate rows. Local Codex session-log paths stay in
`local_state/` and are not published.
The summary page also plots ProgramBench-style behavioral pass-rate
distributions (histogram and cumulative), plus per-task pass rate against
estimated cost, Codex calls, and wall-clock latency. Calls are the public
compute proxy; raw token logs remain local unless explicitly exported.
For each evaluated instance, the report also writes `docs/task/<instance_id>/`
with a ProgramBench-style task detail page: scored behavioral tests, best score,
results by model/mode, cost, calls, wall time, evidence links, and a link to the
official ProgramBench task page.

ProgramBench's public usage guide documents the per-instance `.eval.json` files
that `programbench eval` writes, including `test_results` and evaluator `log`
metadata. To publish similar evidence without exposing raw Codex traces or local
paths, export sanitized evidence first:

```bash
uv run python scripts/export-public-evidence.py
uv run python scripts/build-report.py \
  local_state/open-sample-results.csv \
  local_state/csview-paper-smoke-results.csv \
  --output-dir docs
```

This writes `docs/evidence/<run>/<instance>/manifest.json`,
`eval-summary.json`, and a size-safe public `eval.json`. The public eval keeps
test statuses and failure messages but redacts evaluator `log.output` payloads
and truncates long captured test text. If the local artifact contains
`usage-audit.json`, that is exported too. Raw Codex JSONL traces and
`submission.tar.gz` files remain local under `local_state/run_artifacts/`
unless explicitly reviewed and published.

Refresh the ProgramBench baseline rows before rebuilding the public report:

```bash
uv run python scripts/refresh-programbench-baselines.py
```

The report publishes `docs/data/results.json`, `docs/data/results.csv`, the
refreshed `programbench-baselines.json`, per-run detail pages under `docs/run/`,
and public evidence under `docs/evidence/`.

Before pushing a large report, check the static artifact size budget:

```bash
uv run python scripts/check-docs-size.py
```

The summary page does not load public eval files automatically; it links to
them. That keeps the main page usable for all 200 tasks while still preserving
click-through evidence per instance.

## Pilot Order

1. Near-miss conversion set in `target_sets/first_batch_near_miss.txt`.
2. Full xhigh almost-resolved set in `target_sets/gpt55_xhigh_almost_resolved.txt`.
3. Iconic follow-ups in `target_sets/iconic_followups.txt`.
4. A random control slice for generality.
