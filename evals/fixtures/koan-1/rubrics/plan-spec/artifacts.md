Grade whether the plan-spec phase produced the expected plan artifact.

The plan-spec phase must produce a plan.md file in the run directory.

PASS when plan.md is present in the all_present set for this phase.
Optionally: PASS requires that plan.md cites at least 3 specific file paths from the actual codebase (not invented or generic paths).

FAIL if plan.md is absent from all_present.

Respond with PASS or FAIL on the last line.
