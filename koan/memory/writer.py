# Write memory entries to disk.

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .types import MemoryEntry


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _slugify(title: str, max_len: int = 50) -> str:
    """Convert a title to a filename-safe slug.

    Truncates at the last word boundary (hyphen) within ``max_len`` so the
    final filename does not end on a meaningless word fragment like ``-on``
    or ``-sc``. Falls back to hard truncation only when the entire ``max_len``
    window contains no hyphen.
    """
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug).strip("-")
    slug = re.sub(r"-+", "-", slug)
    if len(slug) <= max_len:
        return slug
    cut = slug[:max_len]
    last_hyphen = cut.rfind("-")
    if last_hyphen > 0:
        cut = cut[:last_hyphen]
    return cut.rstrip("-")


def _next_sequence_number(directory: Path) -> int:
    """Scan ``directory`` for ``NNNN-*.md`` files and return max + 1."""
    pattern = re.compile(r"^(\d{4})-.*\.md$")
    highest = 0
    if directory.is_dir():
        for p in directory.iterdir():
            m = pattern.match(p.name)
            if m:
                highest = max(highest, int(m.group(1)))
    return highest + 1


def _render_frontmatter(entry: MemoryEntry) -> str:
    """Render YAML frontmatter for an entry."""
    meta: dict = {
        "title": entry.title,
        "type": entry.type,
        "created": entry.created,
        "modified": entry.modified,
    }
    if entry.related:
        meta["related"] = entry.related

    return yaml.dump(
        meta,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=False,
    ).rstrip("\n")


def _render_entry(entry: MemoryEntry) -> str:
    """Render a complete entry file: frontmatter + body."""
    fm = _render_frontmatter(entry)
    return f"---\n{fm}\n---\n\n{entry.body}\n"


def write_entry(entry: MemoryEntry, directory: Path) -> Path:
    """Write a new memory entry to ``directory``.

    Assigns the next available sequence number, generates a filename
    slug, sets ``created``/``modified`` to the current UTC timestamp
    if not already set, and returns the written path.
    """
    directory.mkdir(parents=True, exist_ok=True)
    now = _now_iso()
    if not entry.created:
        entry.created = now
    entry.modified = now

    seq = _next_sequence_number(directory)
    slug = _slugify(entry.title)
    filename = f"{seq:04d}-{slug}.md"
    path = directory / filename
    path.write_text(_render_entry(entry), "utf-8")
    return path


def update_entry(entry: MemoryEntry) -> None:
    """Write an entry back to its existing ``file_path``.

    Preserves ``created``; always refreshes ``modified``.
    """
    if entry.file_path is None:
        raise ValueError("entry has no file_path; use write_entry for new entries")
    entry.modified = _now_iso()
    entry.file_path.write_text(_render_entry(entry), "utf-8")
