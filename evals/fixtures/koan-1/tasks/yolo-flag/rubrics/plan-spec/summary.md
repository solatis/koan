Task-specific criteria for the --yolo task. Appended to the fixture-level plan-spec/summary rubric at grade time.

Beyond the generic plan-spec summary shape, the plan for the --yolo task should explicitly cover:

- How `koan_yield` responds under yolo (recommended-progression hint from the yield's suggestions list).
- How `koan_ask_question` responds under yolo (recommended answer if present, else free-form "use your best judgement").
- Whether and how UI events are emitted for auto-answered interactions (skip / `auto_answered` flag / emit normally and resolve immediately).
- The file or files touched to implement the auto-answering logic, named specifically.

PASS if all four task-specific points are present in the plan-spec summary in addition to the generic categories.
FAIL if any of the four is absent or left at a level of generality that the executor would need to re-decide.

Respond with PASS or FAIL on the last line.
