# evals/_verify_rubric_migration.py
# One-shot equivalence check: compares rubric criteria extracted from
# .md files on disk against the code-resident versions in evals/rubrics.py.
# Run before deleting any .md file.

from __future__ import annotations

import sys
from pathlib import Path

from evals.rubrics import FIXTURE_RUBRICS, TASK_RUBRIC_ADDENDUMS, CROSS_PHASE_RUBRICS


def _extract_bullets(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        s = line.lstrip()
        if s.startswith("- "):
            out.append(s[2:].strip())
        elif s.startswith("* "):
            out.append(s[2:].strip())
    return out


def main() -> int:
    fixtures_dir = Path(__file__).resolve().parent / "fixtures"
    mismatches: list[str] = []

    # Fixture-level
    for md in sorted(fixtures_dir.glob("*/rubrics/*/*.md")):
        # evals/fixtures/<f>/rubrics/<phase_dir>/<section>.md
        fixture_id = md.parents[2].name
        phase_dir = md.parents[0].name
        section = md.stem
        phase = phase_dir.replace("_", "-")
        on_disk = _extract_bullets(md.read_text(encoding="utf-8"))
        in_code = FIXTURE_RUBRICS.get((fixture_id, phase, section), [])
        if on_disk != in_code:
            mismatches.append(
                f"MISMATCH fixture {fixture_id}/{phase}/{section}: "
                f"disk={len(on_disk)}, code={len(in_code)}"
            )

    # Task-addendum
    for md in sorted(fixtures_dir.glob("*/tasks/*/rubrics/*/*.md")):
        fixture_id = md.parents[4].name
        task_id = md.parents[2].name
        phase_dir = md.parents[0].name
        section = md.stem
        phase = phase_dir.replace("_", "-")
        on_disk = _extract_bullets(md.read_text(encoding="utf-8"))
        in_code = TASK_RUBRIC_ADDENDUMS.get(
            (fixture_id, task_id, phase, section), [],
        )
        if on_disk != in_code:
            mismatches.append(
                f"MISMATCH task-addendum {fixture_id}/{task_id}/{phase}/{section}: "
                f"disk={len(on_disk)}, code={len(in_code)}"
            )

    # Cross-phase (body comparison)
    for md in sorted(fixtures_dir.glob("*/tasks/*/cases/*.md")):
        fixture_id = md.parents[3].name
        task_id = md.parents[1].name
        case_id = md.stem
        text = md.read_text(encoding="utf-8")
        # Split on the closing --- line (second occurrence).
        lines = text.splitlines(keepends=True)
        try:
            first = next(i for i, L in enumerate(lines) if L.rstrip("\n\r") == "---")
            second = next(i for i, L in enumerate(lines[first+1:], start=first+1)
                          if L.rstrip("\n\r") == "---")
        except StopIteration:
            mismatches.append(f"MISMATCH case {fixture_id}/{task_id}/{case_id}: "
                              f"malformed frontmatter")
            continue
        body_disk = "".join(lines[second+1:]).lstrip("\n").rstrip()
        body_code = CROSS_PHASE_RUBRICS.get(
            (fixture_id, task_id, case_id), "",
        ).rstrip()
        if body_disk != body_code:
            mismatches.append(
                f"MISMATCH cross-phase {fixture_id}/{task_id}/{case_id}: "
                f"disk_len={len(body_disk)}, code_len={len(body_code)}"
            )

    if mismatches:
        for m in mismatches:
            print(m)
        return 1
    print("OK: all rubric data matches between disk and code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
