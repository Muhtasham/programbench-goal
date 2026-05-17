You are solving a ProgramBench task.

ProgramBench asks an agent to rebuild a command-line program from scratch. You
are given only a compiled target binary and documentation already present in the
cleanroom target container.

Your task is to implement a complete replacement codebase in the current
solution directory.

Rules:

- Do not use the internet, package registries, public source repositories,
  external documentation, ProgramBench tests, or evaluator files.
- Do not inspect parent or sibling directories. Treat the current directory as
  the only useful workspace.
- Do not read, decompile, disassemble, trace, instrument, copy, or wrap the
  target binary.
- Learn behavior only through normal CLI/stdin/stdout/stderr/filesystem
  interaction with the target and through documentation bundled in the target
  container.
- Implement the replacement yourself. Do not depend on the target binary or any
  prebuilt copy of it.
- Provide a `compile.sh` script that creates the final `./executable`.
- Run `package-submission` before finishing.

Context:

- Instance: `{{instance_id}}`
- Run: `{{run_name}}`
- Target container image: `{{image}}:task_cleanroom`
- Target command form: `{{target_command}}`
- Package command: `{{package_command}}`
- Solution directory: `{{solution_dir}}`

Suggested loop:

1. Inspect the bundled documentation in the target container.
2. Probe documented behavior through the target command.
3. Build the smallest complete replacement that matches observed behavior.
4. Compare your executable against the target on representative inputs.
5. Fix mismatches and repeat until the implementation is ready.
6. Run `package-submission`.

Keep your work inside the solution directory.
