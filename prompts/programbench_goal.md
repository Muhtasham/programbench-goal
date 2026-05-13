You are solving a ProgramBench cleanroom task.

Objective:
Reimplement the target CLI from scratch by observing only the target binary and
any documentation already present in the no-network target container.

ProgramBench constraints:
- This is a free-form reimplementation task. Choose the language, architecture,
  source layout, abstractions, and build approach yourself.
- There are no method signatures, skeletons, product requirements, hidden hints,
  or natural-language implementation guidance beyond the executable behavior
  and in-container documentation.
- Do not tune the harness or solution for a known test suite. The final answer is
  judged by fully resolved instances; partial pass rate is only diagnostic.

Hard rules:
- Do not use the internet, web search, package managers, GitHub, upstream source
  repositories, decompilers, disassemblers, or source-code recovery tools.
- Do not use tracing or instrumentation tools on the target executable, such as
  `strace`, `ltrace`, debuggers, syscall tracers, profilers, or similar tools.
- Do not inspect the ProgramBench evaluator repository or hidden tests.
- Do not inspect files outside `{{solution_dir}}`, except by interacting with
  the target through the allowed `docker exec -u agent ...` command.
- Interact with the target only through this container:
  `docker exec -u agent {{container_name}} bash -lc '<command>'`
- The target executable is `/workspace/executable` inside that container.
- Use only documentation already present in the cleanroom container. If docs are
  missing or incomplete, do not fetch or supply replacements from outside the
  container.
- Write the complete replacement codebase in:
  `{{solution_dir}}`
- Produce a `compile.sh` at the solution root.
- `compile.sh` must build or copy the final executable to:
  `./executable`

Run context:
- Instance: `{{instance_id}}`
- Target image: `{{image}}:task_cleanroom`
- Target container: `{{container_name}}`
- Solution directory: `{{solution_dir}}`

Complete the implementation in `{{solution_dir}}` so it is ready to package as a
ProgramBench submission.
