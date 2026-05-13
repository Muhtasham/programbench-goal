You are solving a ProgramBench-inspired reconstruction task in open-internet research mode.

This mode is not ProgramBench-compliant and must not be reported as a cleanroom
benchmark result. The purpose is to see what Codex `/goal` can do on the same
task set when normal external resources are allowed.

Task:
- Reconstruct the target CLI and produce a packageable replacement codebase.
- You may use internet access, package managers, public documentation, and public source if useful.
- You may not submit a wrapper around the provided target binary.
- You may not make the final executable depend on `/workspace/executable` or any other prebuilt copy of the same tool.
- You may inspect the target executable only by running it through its normal user interface.
- Write the complete replacement codebase in `{{solution_dir}}`.
- Produce `compile.sh` at the solution root.
- `compile.sh` must build or copy the final executable to `./executable`.
- You may execute `../package-submission.sh` to verify packaging.

Harness context:
- Instance: `{{instance_id}}`
- Target image: `{{image}}:task_cleanroom`
- Target container: `{{container_name}}`
- Solution directory: `{{solution_dir}}`
- Probe the target with:
  `{{target_command}}`
- The target executable is `/workspace/executable` inside that container.
- Bundled documentation is inside `/workspace` in that container.

Complete the implementation in `{{solution_dir}}` so it is ready to package.

Do not mark the goal complete until `compile.sh` exists, `./compile.sh`
succeeds, `./executable` exists and runs, and `../package-submission.sh`
succeeds.
