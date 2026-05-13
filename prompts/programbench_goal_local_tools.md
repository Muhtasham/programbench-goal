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
- You may not submit a wrapper around the provided target binary.
- You may not make the final executable depend on `/workspace/executable` or any
  other prebuilt copy of the same tool.
- Write the complete replacement codebase in `{{solution_dir}}`.
- Produce `compile.sh` at the solution root.
- `compile.sh` must build or copy the final executable to `./executable`.
- You may execute `../package-submission.sh` to verify packaging.

Harness context:
- Instance: `{{instance_id}}`
- Target image: `{{image}}:task_cleanroom`
- Target container: `{{container_name}}`
- Solution directory: `{{solution_dir}}`
- Probe or inspect the target with:
  `{{target_command}}`
- The target executable is `/workspace/executable` inside that container.
- Bundled documentation is inside `/workspace` in that container.

Complete the implementation in `{{solution_dir}}` so it is ready to package.

Do not mark the goal complete until `compile.sh` exists, `./compile.sh`
succeeds, `./executable` exists and runs, and `../package-submission.sh`
succeeds.
