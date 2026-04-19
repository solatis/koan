Grade whether the plan-spec phase produced a coherent, codebase-grounded plan.

Check the following:

- No invented paths. Every file path cited in plan.md must plausibly exist in the koan codebase. Paths like `koan/web/mcp_endpoint.py`, `koan/state.py`, `koan/driver.py` are real; invented module names are a red flag.
- References real function or module names. The plan cites at least a few specific function names, class names, or variable names that actually appear in the codebase.
- Internally consistent. The approach described in the plan does not contradict itself across sections.
- Scoped appropriately. The plan addresses only what the task asked for; it does not propose unrelated refactors or scope creep.

PASS if all four criteria are met.
FAIL if any criterion is violated.

Respond with PASS or FAIL on the last line.
