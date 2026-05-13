# ProgramBench Paper Compliance

This runner is a Codex `/goal` scaffold for ProgramBench, not the paper's
mini-SWE-agent baseline. Report it as a separate scaffold.

The default `paper` inference mode is the cleanroom mode. The optional
`open-internet` mode is intentionally non-compliant and exists only for
ProgramBench-inspired exploratory runs.

| Paper / FAQ requirement | Runner status |
| --- | --- |
| Agent receives compiled executable plus bundled documentation | Uses `task_cleanroom` images and points Codex at `/workspace/executable` plus `/workspace` docs through `docker exec -u agent`. |
| No internet during inference | Target container runs with `--network none`; Codex host still needs OpenAI access, so a Linux host egress guard or equivalent VM policy is required for publishable runs. |
| Loopback networking remains available for network-tool tasks | Docker `--network none` keeps container loopback. External egress is disabled. |
| Execute-only target binary | `check-compliance.sh` verifies the `agent` user can execute but cannot read or inspect `/workspace/executable`. |
| No decompilers, disassemblers, tracing, or instrumentation on target | Prompt forbids it, guard wrappers block common tools, and `scripts/audit-run.py` scans Codex JSONL commands. |
| No source lookup, package registries, external docs, or cached dependency source | Prompt forbids it, guard wrappers block source-acquisition commands, per-run empty tool caches are exported, and audit scans for package/cache lookup patterns. |
| No wrapper/reuse of original binary | ProgramBench eval removes original-binary hashes. Runner packaging excludes harness-only rules, and audit scans solution files/archive for obvious target delegation patterns. |
| Free-form implementation, any language | Prompt preserves free-form choice. Guard wrappers allow local build/test commands while blocking acquisition commands. |
| Paper resources | Defaults to 20 CPUs and 60GB RAM; `--strict-paper` audit flags deviations. |
| Paper run limits | `/goal` is not mini-SWE-agent, so 1,000-step and 6-hour limits are not enforced identically. Report actual elapsed time and Codex call count from logs. |
| Per-action timeout and output truncation | Codex CLI behavior is not identical to mini-SWE-agent's 3-minute action timeout and 10k-character output truncation. Disclose this as a scaffold difference. |
| Scoring | `scripts/summarize-results.py` imports ProgramBench scoring code, filters active branches/ignored tests, and reports resolved, almost-resolved, average pass rate, calls, tokens, and estimated cost. |
| Evaluation | Uses ProgramBench's own `programbench eval` and `programbench info`; evaluation may fetch test blobs, which is evaluator-side, not inference-side. |

Open-internet mode:

- Allows normal host internet/package/source use.
- Starts the target container with normal Docker bridge networking.
- Uses a prompt that explicitly labels the run non-compliant.
- Still forbids final wrappers around `/workspace/executable`.
- Must be reported separately from cleanroom ProgramBench results.

Minimum bar before public reporting:

1. Run on Linux `amd64`, not macOS/ARM64 emulation.
2. Run Codex under a dedicated user or VM whose outbound network permits only required OpenAI/Codex endpoints.
3. Run `check-compliance.sh` before inference.
4. Run `scripts/audit-run.py --strict-paper <instance-dir>` after inference.
5. Evaluate with ProgramBench and summarize with ProgramBench scoring logic.
6. Report as "Codex GPT-5.5 `/goal` scaffold", not mini-SWE-agent.
