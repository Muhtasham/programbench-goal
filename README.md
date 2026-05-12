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

The Codex launcher uses YOLO mode:

```bash
codex --enable goals -m gpt-5.5 -c model_reasoning_effort='xhigh' \
  -s danger-full-access -a never --no-alt-screen
```

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

## Quickstart

Prepare a `jq` run:

```bash
uv run python programbench_goal_runner.py prepare jqlang__jq.b33a763
```

Prepare with an official prompt template when one is available:

```bash
uv run python programbench_goal_runner.py prepare jqlang__jq.b33a763 \
  --prompt-template /path/to/official-programbench-prompt.md
```

Prepare the near-miss first batch:

```bash
uv run python programbench_goal_runner.py prepare-batch target_sets/first_batch_near_miss.txt
```

Start the no-network target container:

```bash
~/pb-goal-runs/gpt55-goal-jq/jqlang__jq.b33a763/start-target.sh
```

Check the compliance-critical container properties:

```bash
~/pb-goal-runs/gpt55-goal-jq/jqlang__jq.b33a763/check-compliance.sh
```

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

The summary reports fully resolved rate, almost-resolved rate (`score > 0.95`,
matching ProgramBench's FAQ wording), average pass rate, Codex calls, token
usage, and estimated cost. The CSV includes the exact Codex JSONL `session_logs`
used for each instance, so usage numbers can be audited directly. Codex CLI
session logs expose token counts and call counts, but not authoritative dollars.
Set these environment variables to estimate cost from current pricing:

```bash
export CODEX_INPUT_USD_PER_MTOK=...
export CODEX_CACHED_INPUT_USD_PER_MTOK=...
export CODEX_OUTPUT_USD_PER_MTOK=...
```

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

## Pilot Order

1. Near-miss conversion set in `target_sets/first_batch_near_miss.txt`.
2. Full xhigh almost-resolved set in `target_sets/gpt55_xhigh_almost_resolved.txt`.
3. Iconic follow-ups in `target_sets/iconic_followups.txt`.
4. A random control slice for generality.
