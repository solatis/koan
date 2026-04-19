Grade the overall behavior of the orchestrator during the intake phase.

Check the following cross-cutting behaviors:

- Scout discipline. The orchestrator launches scouts only when the task genuinely requires broad codebase investigation. For a trivial, self-contained change, scouts are unnecessary overhead and signal misjudgment of task complexity.
- Memory usage. The orchestrator either calls `koan_search` or reads memory files directly from `.koan/memory/`. Bonus if `koan_search` is used rather than raw file reads, because the tool is the intended retrieval surface.
- Codebase grounding. The orchestrator opens the files the task description references and verifies claims against what it reads, rather than taking the task description at face value.

PASS if all three behaviors are observed.
FAIL if any of the three behaviors is absent.

Respond with PASS or FAIL on the last line.
