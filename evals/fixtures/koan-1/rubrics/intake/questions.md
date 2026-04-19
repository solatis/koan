Grade the questions the orchestrator raised during the intake phase.

A well-performing intake should surface targeted, non-obvious questions. Look for:

- Questions that flag contradictions, inaccuracies, or mistakes in the task description -- the orchestrator cross-references the claim against the actual codebase and surfaces any discrepancy.
- Questions that probe the expected behavior of APIs or system surfaces the task touches, when the task description does not specify.
- Questions that seek the broader use case or intent behind the requested change, to ground scope decisions.
- Questions that resolve ambiguity about downstream effects the task description is silent on (e.g. side effects on UI, events, persistence).

Generic questions already answerable from the task text (e.g. "what is the deadline?") do not count. Questions that could be resolved by reading the codebase alone do not count.

PASS if the orchestrator raised at least two targeted questions of the kinds above.
FAIL if the questions were generic, redundant with the task, or if no substantive questions were raised.

Respond with PASS or FAIL on the last line.
