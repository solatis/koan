Task-specific criteria for the --yolo task. Appended to the fixture-level plan-spec/overall rubric at grade time.

Beyond the generic plan-spec coherence checks, the plan for the --yolo task should:

- Stay scoped to the interaction-gate auto-answering behavior. The plan does not propose broader refactors of the runner subsystem, the permission fence, or unrelated CLI surface.
- Not contradict the existing --yolo usage. The plan does not break or regress the existing codex / gemini "accept everything" behavior controlled by `_YOLO_ARGS` in `koan/web/app.py`.
- Name the actual auto-response integration point (the `koan_yield` and `koan_ask_question` tool handlers in `koan/web/mcp_endpoint.py`) rather than an invented indirection layer.

PASS if all three task-specific criteria are met.
FAIL if any is violated.

Respond with PASS or FAIL on the last line.
