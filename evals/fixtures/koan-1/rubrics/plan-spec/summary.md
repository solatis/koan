Grade the summary the orchestrator produced at the end of the plan-spec phase.

A good plan-spec summary should cover:

- Approach: a clear description of the overall strategy for the implementation.
- Key decisions: the architectural or design choices made, each with a one-line rationale.
- Files to touch: specific file paths from the actual codebase that will be modified, not generic module names.
- Ordering: the sequence in which changes will be applied, with any dependencies between steps called out.

PASS if the summary addresses all four categories with enough specificity that an engineer could begin implementation without further research.
FAIL if the summary is vague, omits key decisions, or does not name specific files.

Respond with PASS or FAIL on the last line.
