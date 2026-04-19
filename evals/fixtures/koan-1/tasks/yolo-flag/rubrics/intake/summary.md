Task-specific criteria for the --yolo task. These are appended to the fixture-level intake/summary rubric at grade time.

Beyond the generic summary shape, the intake summary for the --yolo task should also contain:

- The existing --yolo usage in the codex and gemini runner paths (koan/web/app.py `_YOLO_ARGS`), and the fact that this is unrelated to the user-interaction auto-answering behavior being asked for.
- The chosen return-value semantics for `koan_yield` (recommended-progression hint) and `koan_ask_question` (recommended answer or "use your best judgement") in yolo mode.
- The chosen UI-event treatment (skip / auto_answered flag / emit-and-resolve-immediately) and rationale.
- The corrected framing of the original task description: --yolo is not a no-op globally; it currently has no effect on koan's own interaction gates.
- The broader use case (eval automation / unsupervised runs) as the reason the auto-answering behavior is wanted.

PASS if at least 3 of the above task-specific points are present in addition to the generic categories.
FAIL if the summary discusses --yolo only abstractly without the task-specific context above.

Respond with PASS or FAIL on the last line.
