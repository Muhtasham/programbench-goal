You are solving a ProgramBench cleanroom task.

Objective:
Reimplement the target CLI from scratch by observing only the target binary and
any documentation already present in the no-network target container.

Hard rules:
- Do not use the internet, web search, package managers, GitHub, upstream source
  repositories, decompilers, disassemblers, or source-code recovery tools.
- Do not inspect the ProgramBench evaluator repository or hidden tests.
- Interact with the target only through this container:
  `docker exec -u agent {{container_name}} bash -lc '<command>'`
- Use only documentation already present in the cleanroom container. If docs are
  missing or incomplete, do not fetch or supply replacements from outside the
  container.
- Write the complete replacement codebase in:
  `{{solution_dir}}`
- Produce a `compile.sh` at the solution root.
- `compile.sh` must build or copy the final executable to:
  `./executable`

Recommended loop:
1. Inventory what files and documentation exist in the target container.
2. Probe the target binary behavior with many focused examples.
3. Implement the smallest faithful replacement.
4. Build with `./compile.sh`.
5. Compare your executable against the target binary on your own generated cases.
6. Keep expanding coverage and fixing mismatches.

Run context:
- Instance: `{{instance_id}}`
- Target image: `{{image}}:task_cleanroom`
- Target container: `{{container_name}}`
- Solution directory: `{{solution_dir}}`

Spend the long horizon on behavior, not explanations. Keep iterating until the
implementation is ready to package as a ProgramBench submission.
