# ProgramBench Goal Runner

Small harness for running Codex GPT-5.5 `/goal` against ProgramBench cleanroom
tasks.

The harness keeps the solving workspace separate from the ProgramBench evaluator
repo. It starts the target binary inside a no-network Docker container, gives
Codex a clean writable solution directory, and produces the `submission.tar.gz`
layout that `programbench eval` expects.

## Requirements

- Linux `amd64` host for real runs.
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

## Quickstart

Prepare a `jq` run:

```bash
python3 programbench_goal_runner.py prepare jqlang__jq.b33a763
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

## Pilot Order

1. `testorg__calculator.abc1234` to verify packaging and evaluation mechanics.
2. `wfxr__csview.8ac4de0` or `sclevine__yj.8016400` for a realistic small CLI.
3. `jqlang__jq.b33a763` for the serious long run.
4. `ffmpeg__ffmpeg.360a402` only after the harness proves itself on smaller tasks.
