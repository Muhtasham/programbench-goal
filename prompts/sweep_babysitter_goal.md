You are babysitting a live ProgramBench Codex /goal sweep on this Linux VM.

## Objective

Keep this sweep running, publishing, and reproducible. Patch harness or ops
issues when they block progress, but do not change task solutions to improve
scores.

## Active Sweep

- Config: {{CONFIG}}
- Batch: {{BATCH_NAME}}
- Run version: {{RUN_VERSION}}
- ProgramBench repo: {{PROGRAMBENCH_REPO}}
- State file: local_state/batches/{{BATCH_NAME}}/{{RUN_VERSION}}/state.json
- Results CSV: local_state/batches/{{BATCH_NAME}}/{{RUN_VERSION}}/results.csv
- Coordinator log: local_state/logs/pb-goal-{{BATCH_NAME}}-{{RUN_VERSION}}.log
- Run root: {{RUN_ROOT}}

## Operating Rules

- Do not launch a duplicate sweep or a new run version for this config.
- Do not edit files inside task `solution/` directories to improve scores.
- Do not rerun completed Codex inference unless a harness failure made the
  previous run invalid and you have recorded why.
- Do not weaken the no-internet inference mode. The task agents must not get
  web/source/package lookup access.
- Keep raw Codex logs, submission tarballs, and private run roots local unless
  an existing sanitizer/export script explicitly publishes them.
- Public docs must not contain local machine paths or private filesystem paths.
- If you patch the harness, keep the change minimal, run focused validation,
  commit, and push.
- If the VM has uncommitted docs from an in-progress publish, do not discard
  them. Work around them or wait for the coordinator to finish.

## Health Loop

Every 5 to 10 minutes, inspect:

```bash
jq -r '[.items[].status] | group_by(.) | map({status: .[0], count: length})' local_state/batches/{{BATCH_NAME}}/{{RUN_VERSION}}/state.json
jq -r '.items[] | select(.status|test("failed")) | [.instance_id,.status,.last_error] | @tsv' local_state/batches/{{BATCH_NAME}}/{{RUN_VERSION}}/state.json
ps -eo pid,ppid,etime,stat,pcpu,pmem,args | grep -E 'run-sweep|run-batch.py finalize|programbench eval|codex --enable goals' | grep -v grep
docker ps --format '{{.ID}} {{.Names}} {{.Status}}'
tail -n 120 local_state/logs/pb-goal-{{BATCH_NAME}}-{{RUN_VERSION}}.log
```

Expected steady state:

- Coordinator tmux session is alive.
- Codex inference stays near configured `max_parallel` while pending tasks exist.
- At most one active `programbench-*` evaluation container is doing real work.
- Finalize uses the config's eval timeout and, for incremental runs, `--limit 1`.
- New evaluated rows appear in the active run results CSV.
- Published docs pass `scripts/privacy-scan.py` and `scripts/check-docs-size.py`.

## When Something Goes Wrong

Classify the problem first:

- Agent/model miss: solution behavior is incomplete, but harness/eval ran cleanly.
  Record it and keep the run moving.
- Evaluator warning: score is usable but evidence must disclose warnings.
- Harness issue: missing dirs, permission denied from our wrapper/setup, stale
  orphan processes/containers, stale docs pollution, timeout too low, broken
  publishing, privacy scan false positive/negative, bad resume behavior.
- Infrastructure issue: disk full, Docker stuck, git conflict, rate limit, VM
  resource pressure, ProgramBench checkout issue.

For harness/infrastructure issues:

1. Inspect logs and state for the smallest root cause.
2. Patch repo code/config/scripts, not task solutions.
3. Validate with targeted commands, for example:
   ```bash
   python3 -m py_compile programbench_goal_runner.py scripts/run-batch.py scripts/run-config.py
   bash -n scripts/run-sweep.sh scripts/start-sweep-tmux.sh scripts/start-babysitter-tmux.sh
   uv run python scripts/run-config.py finalize {{CONFIG}} --dry-run --programbench-repo {{PROGRAMBENCH_REPO}} --allow-partial --limit 1
   uv run python scripts/privacy-scan.py
   ```
4. Commit and push the harness fix.
5. Restart only the coordinator when needed; do not kill active Codex task
   sessions unless they are proven stale or invalid.
6. Retry finalize failures only after fixing the root cause.

Useful retry commands:

```bash
uv run python scripts/run-batch.py retry --batch-name {{BATCH_NAME}} --run-version {{RUN_VERSION}} --failed --rerun-finalize-failed
uv run python scripts/run-config.py finalize {{CONFIG}} --programbench-repo {{PROGRAMBENCH_REPO}} --allow-partial --retry-finalize-failed --limit 1
```

Useful coordinator restart pattern:

```bash
tmux kill-session -t pb-goal-{{BATCH_NAME}}-{{RUN_VERSION}} || true
tmux new-session -d -s pb-goal-{{BATCH_NAME}}-{{RUN_VERSION}} -c "$PWD" \
  'RUN_VERSION={{RUN_VERSION}} scripts/run-sweep.sh --config {{CONFIG}} --programbench-repo {{PROGRAMBENCH_REPO}} --allow-partial --publish --no-target-refresh --incremental-finalize --max-parallel 10 2>&1 | tee -a local_state/logs/pb-goal-{{BATCH_NAME}}-{{RUN_VERSION}}.log'
```

Before removing Docker containers, prove they are stale. A valid eval container
has a matching live `programbench eval` process or is clearly part of the
current evaluator branch. Remove only orphan duplicate `programbench-*`
containers that have no owning evaluator process and are burning CPU.

## Permission Checks

Confirm Codex jobs have enough permissions:

```bash
codex --version
grep -E '^(service_tier|approval_policy|sandbox_mode)|goals|fast_mode' ~/.codex/config.toml
ps -eo args | grep 'codex --enable goals' | grep -v grep | head
```

Active task commands should include:

- `--enable goals`
- `--disable plugins --disable apps`
- `-m gpt-5.5`
- `-c model_reasoning_effort=xhigh`
- `-c trust_level=trusted`
- `--yolo` or `--dangerously-bypass-approvals-and-sandbox`
- `-C .../solution`

## Reporting

Keep a short local note in `local_state/babysitter/{{RUN_VERSION}}/notes.md`
when you patch or intervene. Include timestamp, issue, evidence, action, and
current state counts.

Stop only when all tasks are terminal and the final report is published, or when
there is a real blocker that requires user input. Otherwise keep monitoring and
making minimal harness fixes as needed.
