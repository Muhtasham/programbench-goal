You are solving a ProgramBench-inspired reconstruction task in no-internet local-tools mode.

This mode is intentionally not ProgramBench-compliant. It measures how far Codex
can get without internet access when it is allowed to use local tools, including
binary-analysis or tracing tools if they are available locally. Do not report
this as a cleanroom ProgramBench result.

Task:
- Reconstruct the target CLI and produce a packageable replacement codebase.
- Do not use internet access, package registries, public source, external docs,
  or cached dependency source from package registries.
- Do not inspect the ProgramBench evaluator repository or hidden tests.
- You may use local installed tools, local scripts, generated probes, fuzzers,
  binary-analysis tools, tracing/instrumentation tools, and tools you write
  yourself.
- You may inspect the provided target binary with local tools in this mode.
- Do not inspect files outside `{{solution_dir}}` on the host, except through
  local target-inspection commands needed for this ablation.
- Do not inspect parent directories, the run root, sibling harness files, or the
  ProgramBench evaluator repository.
- You may not submit a wrapper around the provided target binary.
- You may not make the final executable depend on `/workspace/executable` or any
  other prebuilt copy of the same tool.
- Write the complete replacement codebase in `{{solution_dir}}`.
- Produce `compile.sh` at the solution root.
- `compile.sh` must build or copy the final executable to `./executable`.
- You may execute `{{package_command}}` to verify packaging. Do not inspect the
  implementation of that helper or any files outside `{{solution_dir}}`.

Required behavior-discovery loop:
- Read the bundled documentation in `/workspace` through the target container.
- Build a feature inventory from docs, `--help`/version output, obvious flags,
  stdin/stdout/stderr behavior, exit codes, filesystem effects, config/env
  behavior, terminal/no-terminal behavior, invalid inputs, boundary cases, and
  combinations of documented options.
- For every documented option that accepts a value, probe valid and invalid
  values, case variants where values are words, and combinations with
  help/version or other early-exit flags. Do not assume option parsing is
  case-sensitive or that earlier options are ignored before `-h`/`-V`.
- Maintain `.goal/BEHAVIOR_AUDIT.md` in the solution directory. Keep it updated
  with the feature inventory, probe commands, target-vs-local comparison
  results, discrepancies found, fixes made, remaining known gaps, and the final
  stopping rationale. The harness excludes `.goal/` and `probes/` from the
  submitted archive. Put generated target probes and scratch comparison
  fixtures under `probes/`.
- After the first implementation works, continue running target-vs-local
  comparison probes and fix mismatches. Use generated probes/fuzzers where they
  help.
- `{{package_command}}` succeeding is only a packaging gate. It is not enough to
  finish the goal.

Harness context:
- Instance: `{{instance_id}}`
- Target image: `{{image}}:task_cleanroom`
- Target container: `{{container_name}}`
- Solution directory: `{{solution_dir}}`
- Probe or inspect the target with:
  `{{target_command}}`
- The target executable is `/workspace/executable` inside that container.
- Bundled documentation is inside `/workspace` in that container.
- Your shell already starts in the solution directory. Use relative paths and
  do not set explicit workdirs or copy absolute solution paths into commands.

Complete the implementation in `{{solution_dir}}` so it is ready to package.

Do not mark the goal complete until `compile.sh` exists, `./compile.sh`
succeeds, `./executable` exists and runs, `{{package_command}}` succeeds, and
`.goal/BEHAVIOR_AUDIT.md` documents broad target-vs-local behavioral coverage
with no obvious high-impact gaps left to investigate.
