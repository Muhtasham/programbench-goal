You are solving a ProgramBench-inspired reconstruction task in no-internet Codex `/goal` mode.

This mode is for measuring how far Codex can get when external internet,
package registries, upstream source lookup, and external documentation are not
available. It is a Codex scaffold ablation, not an official mini-SWE-agent
ProgramBench baseline.

Task:
- Reconstruct the target CLI and produce a packageable replacement codebase.
- Do not use internet access, package registries, public source, external docs,
  or cached dependency source.
- Do not use web search, browser tools, `curl`, `wget`, package-manager
  downloads, or any external network resource to learn implementation details.
- Do not submit a wrapper around the provided target binary.
- Do not make the final executable depend on `/workspace/executable` or any
  other prebuilt copy of the same tool.
- Do not decompile, disassemble, trace, instrument, or inspect the target binary.
- You may only learn target behavior by running it through its normal user
  interface: CLI flags, stdin/stdout, filesystem effects, and localhost behavior.
- You may write your own black-box probes, fuzzers, generators, and comparison
  scripts that interact with the target only through normal runtime behavior.
- Do not inspect files outside `{{solution_dir}}` on the host.
- Do not run host commands against `..`, parent directories, the run root, or
  any sibling harness files. Parent-directory inspection is disqualifying.
- Do not inspect the ProgramBench evaluator repository or hidden tests.
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
- Maintain `.goal/BEHAVIOR_AUDIT.md` in the solution directory. Keep it updated
  with the feature inventory, probe commands, target-vs-local comparison
  results, discrepancies found, fixes made, remaining known gaps, and the final
  stopping rationale. The harness excludes `.goal/` from the submitted archive.
- After the first implementation works, continue running target-vs-local
  comparison probes and fix mismatches. Use generated probes/fuzzers where they
  help. Do not use hidden tests or evaluator files.
- `{{package_command}}` succeeding is only a packaging gate. It is not enough to
  finish the goal.

Harness context:
- Instance: `{{instance_id}}`
- Target image: `{{image}}:task_cleanroom`
- Target container: `{{container_name}}`
- Solution directory: `{{solution_dir}}`
- Probe the target with:
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
