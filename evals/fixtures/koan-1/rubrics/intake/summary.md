Grade the summary the orchestrator produced at the end of the intake phase.

A good intake summary should contain:

- Task scope: a concise statement of what is being built or changed and which user-facing or internal surfaces are affected.
- Findings relevant for planning: specific existing code patterns, constraints, or integration points the planner will need.
- Decisions made during intake: explicit answers to ambiguities that surfaced in the questions phase.
- Newly discovered context and rationale: facts about the codebase or the problem that were not obvious from the task description.
- Architecture / component points: the files or modules the implementation will likely touch, named specifically.

PASS if the summary covers at least 4 of the above categories with substantive, specific content (not generic platitudes).
FAIL if the summary is vague, missing key findings, omits decisions and rationale, or is notably shorter than what the evidence collected during intake would support.

Respond with PASS or FAIL on the last line.
