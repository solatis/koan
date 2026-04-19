# Project summary generation for the flat memory directory.

from __future__ import annotations

import logging
import re

from .llm import generate
from .store import MemoryStore
from .types import MemoryEntry

log = logging.getLogger("koan.memory.summarize")


_SUMMARY_SYSTEM = """\
You are a technical writer producing a project summary for AI coding
agents. This summary is the first thing an agent reads when starting
any task on this project. It must answer: what is this project, how
is it built, what constraints are in effect, and what mistakes to
avoid.

Rules:
- Write a briefing document with clear markdown sections
- Preserve concrete details: version numbers, tool names, exact
  constraints
- Include a "Known pitfalls" section if lessons exist
- Stay under 2000 tokens
- Do not include information not supported by the provided knowledge"""


def _render_entries_for_prompt(entries: list[MemoryEntry]) -> str:
    """Concatenate entry titles + bodies for LLM prompt context."""
    parts: list[str] = []
    for e in entries:
        parts.append(f"### {e.title} ({e.type}, {e.created})\n\n{e.body}")
    return "\n\n---\n\n".join(parts)


def _seq_number(entry: MemoryEntry) -> int:
    """Extract the NNNN prefix from an entry's filename."""
    if entry.file_path is None:
        return 0
    m = re.match(r"^(\d{4})-", entry.file_path.name)
    return int(m.group(1)) if m else 0


async def generate_summary(
    store: MemoryStore,
    project_name: str = "",
) -> str:
    """Generate summary.md by reading all entries directly."""
    entries = store.list_entries()

    if not entries:
        log.debug("generate_summary: no entries, writing empty summary")
        summary = "No memory entries exist yet."
        store._memory_dir.mkdir(parents=True, exist_ok=True)
        (store._memory_dir / "summary.md").write_text(summary + "\n", "utf-8")
        return summary

    context = _render_entries_for_prompt(entries)
    heading = project_name if project_name else "this project"
    prompt = (
        f"Below are all active memory entries for {heading}.\n"
        f"Write a project summary briefing document.\n\n"
        f"{context}"
    )

    log.info("generate_summary: sending %d entries (%d chars) to LLM", len(entries), len(context))
    try:
        summary = await generate(prompt, system=_SUMMARY_SYSTEM, max_tokens=2500)
        log.info("generate_summary: LLM returned %d chars", len(summary))
    except Exception:
        log.exception("LLM call failed for project summary generation")
        raise

    summary = summary.strip()
    store._memory_dir.mkdir(parents=True, exist_ok=True)
    (store._memory_dir / "summary.md").write_text(summary + "\n", "utf-8")
    log.debug("generate_summary: wrote summary.md (%d chars)", len(summary))
    return summary


async def regenerate_summary(
    store: MemoryStore,
    project_name: str = "",
) -> None:
    """Regenerate the project summary after entries change."""
    await generate_summary(store, project_name=project_name)
