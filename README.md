# ProgramBench Goal Runner

Small harness for running Codex GPT-5.5 `/goal` against ProgramBench cleanroom
tasks.

This is a Codex `/goal` scaffold, not the official mini-SWE-agent baseline
scaffold. It uses ProgramBench's Docker task images and evaluation code, but the
inference loop is Codex CLI goal mode. Report results as Codex `/goal` results,
not as mini-SWE-agent results.

The harness keeps the solving workspace separate from the ProgramBench evaluator
repo. It starts the target binary inside a no-network Docker container, gives
Codex a clean writable solution directory, and produces the `submission.tar.gz`
layout that `programbench eval` expects.

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
- Codex CLI with `features.goals = true`.
- `tmux`.
- A separate ProgramBench checkout only for evaluation.

The ProgramBench images are published for `linux/amd64`. Docker Desktop on Apple
Silicon can sometimes emulate them, but serious runs should happen on Linux
`amd64`.

## Isolation Model

The target binary runs in a Docker container with `--network none`, so probes
against the original program cannot reach the internet. The generated prompt
also requires probing through `docker exec -u agent ...`; this matters because
the cleanroom executable is execute-only for the `agent` user, while root can
bypass file permissions.

Codex itself runs on the host because it must reach OpenAI. The generated prompt
forbids internet use, package managers, upstream source lookup, decompilers, the
ProgramBench evaluator repository, and external replacement docs for images with
missing documentation. The launcher does not enable web search. If you need hard
enforcement for host shell commands too, run this harness inside a VM or host
environment with an egress policy that only permits Codex/OpenAI traffic.

For stricter runs, avoid giving the Codex user direct Docker socket access.
Install the narrow target wrapper and prepare runs with `--target-access wrapper`:

```bash
sudo install -o root -g root -m 0755 scripts/pb-target-exec /usr/local/bin/pb-target-exec
uv run python programbench_goal_runner.py prepare jqlang__jq.b33a763 \
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

The Codex launcher uses YOLO mode:

```bash
codex --enable goals -m gpt-5.5 -c model_reasoning_effort='xhigh' \
  -s danger-full-access -a never --no-alt-screen
```

Override `--model` and `--reasoning-effort` when preparing runs if you want a
separate high/xhigh sweep. These values are written into `run.json` and the
metrics CSV. Container and `tmux` session names include the run name, so high
and xhigh runs for the same instance can coexist. Default run names include
non-default model or effort values.

The generated target container defaults to the paper's resource setting of 20
CPUs and 60GB RAM. For local smoke tests on smaller machines, pass
`--docker-cpus` and `--docker-memory` to `prepare` or `prepare-batch`; do not
report those local smoke runs as paper-comparable results.

The generated Codex launcher prepends a `guard-bin` directory to `PATH`. It
blocks common host-side internet, source/package lookup, and binary-analysis
commands, restricts `docker` to the allowed
`docker exec -u agent <container> ...` target-probing form, and points common
tool caches at an empty per-run directory. Local build commands such as
`go build` and `cargo build` are still allowed; source-acquisition commands such
as `go get`, `cargo install`, and `pip install` are blocked. Agent-created
black-box probes, fuzzers, generators, and comparison scripts are allowed when
they interact with the target only through normal runtime behavior. This catches
common mistakes. It also blocks common local file-inspection commands from
reading parent directories, the run root, home paths, or the evaluator checkout.
This is still not a replacement for a VM/container/user-level egress policy.

See `docs/paper-compliance.md` for the paper/FAQ compliance matrix.

## Inference Modes

Default mode is `paper`. This is the only mode intended for ProgramBench-style
cleanroom reporting:

```bash
uv run python programbench_goal_runner.py prepare jqlang__jq.b33a763
```

There is also an explicitly non-compliant research mode for
ProgramBench-inspired runs where Codex can use normal internet and package
tooling:

```bash
uv run python programbench_goal_runner.py prepare jqlang__jq.b33a763 \
  --inference-mode open-internet
```

Open-internet runs still produce `submission.tar.gz` and can be evaluated with
ProgramBench, but report them separately as open-internet Codex `/goal`
experiments. Do not mix them with cleanroom ProgramBench results.

## Reporting

Use ProgramBench's resolved, almost-resolved, average pass-rate, cost, and calls
metrics so results are comparable in shape to the leaderboard. Label the scaffold
explicitly, for example: `GPT-5.5 xhigh / Codex goal`, and disclose wall-clock
time, inference mode, host/network enforcement, and any paper deviations. Treat
this as a scaffold comparison against mini-SWE-agent, not an apples-to-apples
model-only comparison.

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
controls. The generated prompts require `docker exec -u agent ...`, but for a
publishable run you should either supervise that boundary or expose only a
narrow wrapper for target execution.

## Metrics

Use ProgramBench's primary metric when reporting results: fully resolved
instances. Almost-resolved and average pass rate are useful diagnostics, but
they should not be the headline score.

Local state lives under `local_state/`, which is ignored by git. Use it for
pricing snapshots, run manifests, copied Codex logs, eval JSON, result CSVs, and
trace bundles that should be shareable locally but not committed.

Refresh OpenAI pricing before summarizing cost:

```bash
uv run python scripts/refresh-openai-pricing.py
```

This writes `local_state/openai_pricing.json` from official OpenAI model docs.
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
uv run python programbench_goal_runner.py prepare-batch target_sets/first_batch_near_miss.txt
```

Prepare the same batch with wrapper-mode target access:

```bash
uv run python programbench_goal_runner.py prepare-batch target_sets/first_batch_near_miss.txt \
  --target-access wrapper
```

For real sweeps, prefer the resumable batch manager so the laptop does not start
too many Codex `/goal` sessions at once:

```bash
uv run python scripts/run-batch.py watch target_sets/first_batch_near_miss.txt \
  --batch-name first-near-miss-xhigh \
  --max-parallel 1 \
  --reasoning-effort xhigh
```

Use `--max-parallel 1` on a laptop until we know the active Codex rate limits.
Use separate batch names for `high`, `xhigh`, `paper`, and `open-internet`
runs. The manager stores resumable state under `local_state/batches/`, starts
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

Start the no-network target container:

```bash
~/pb-goal-runs/gpt55-goal-jq/jqlang__jq.b33a763/start-target.sh
```

Check the compliance-critical container properties:

```bash
~/pb-goal-runs/gpt55-goal-jq/jqlang__jq.b33a763/check-compliance.sh
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
  --instance-dir ~/pb-goal-runs/gpt55-goal-jq/jqlang__jq.b33a763
```

The preflight checks Linux `amd64`, Docker CPU/RAM capacity, dedicated-user
existence, direct Docker-group exposure, OpenAI egress guard status, target
container network mode, and generated guard wrappers.

Launch Codex in `tmux` and inject `/goal`:

```bash
~/pb-goal-runs/gpt55-goal-jq/jqlang__jq.b33a763/start-codex-goal.sh
```

Attach to the session:

```bash
tmux attach -t pb-goal-jqlang-jq-b33a763
```

Package the submission:

```bash
~/pb-goal-runs/gpt55-goal-jq/jqlang__jq.b33a763/package-submission.sh
```

Audit the Codex JSONL trace and package shape before evaluating or reporting:

```bash
uv run python scripts/audit-run.py --strict-paper ~/pb-goal-runs/gpt55-goal-jq/jqlang__jq.b33a763
```

Evaluate from a ProgramBench checkout:

```bash
~/pb-goal-runs/gpt55-goal-jq/jqlang__jq.b33a763/eval-submission.sh /path/to/ProgramBench
```

Summarize leaderboard-style metrics after evaluation:

```bash
uv run --project /path/to/ProgramBench \
  python /path/to/programbench-goal-runner/scripts/summarize-results.py ~/pb-goal-runs/gpt55-goal-jq \
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
pricing.

Set these environment variables to estimate cost from current pricing:

```bash
export CODEX_INPUT_USD_PER_MTOK=...
export CODEX_CACHED_INPUT_USD_PER_MTOK=...
export CODEX_OUTPUT_USD_PER_MTOK=...
```

Collect local evidence for a run after evaluation:

```bash
uv run python scripts/collect-run-artifacts.py ~/pb-goal-runs/gpt55-goal-jq/jqlang__jq.b33a763
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
        last = payload["info"]["total_token_usage"]
print({"calls": calls, "total_token_usage": last})
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

The report keeps `paper` and `open-internet` tracks separate, includes the
ProgramBench-style resolved/almost/average-pass/cost/calls metrics, and commits
only sanitized aggregate rows. Local Codex session-log paths stay in
`local_state/` and are not published.

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
`eval-summary.json`, and a redacted public `eval.json`. If the local artifact
contains `usage-audit.json`, that is exported too. Raw Codex JSONL traces and
`submission.tar.gz` files remain local under `local_state/run_artifacts/`
unless explicitly reviewed and published.

Refresh the ProgramBench baseline rows before rebuilding the public report:

```bash
uv run python scripts/refresh-programbench-baselines.py
```

The report publishes `docs/data/results.json`, `docs/data/results.csv`, the
refreshed `programbench-baselines.json`, per-run detail pages under `docs/run/`,
and public evidence under `docs/evidence/`.

## Pilot Order

1. Near-miss conversion set in `target_sets/first_batch_near_miss.txt`.
2. Full xhigh almost-resolved set in `target_sets/gpt55_xhigh_almost_resolved.txt`.
3. Iconic follow-ups in `target_sets/iconic_followups.txt`.
4. A random control slice for generality.
