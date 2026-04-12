# Write memory entries and indexes to disk.

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .types import MemoryEntry, MemoryIndex


def _slugify(title: str, max_len: int = 50) -> str:
    """Convert a title to a filename-safe slug."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return slug[:max_len].rstrip("-")


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
        "date": entry.date,
        "source": entry.source,
        "status": entry.status,
    }
    if entry.tags:
        meta["tags"] = entry.tags
    if entry.supersedes is not None:
        meta["supersedes"] = entry.supersedes
    else:
        meta["supersedes"] = None
    if entry.related:
        meta["related"] = entry.related

    return yaml.dump(meta, default_flow_style=None, sort_keys=False, allow_unicode=False).rstrip("\n")


def _render_entry(entry: MemoryEntry) -> str:
    """Render a complete entry file: frontmatter + intro + body."""
    fm = _render_frontmatter(entry)
    return f"---\n{fm}\n---\n\n{entry.contextual_introduction}\n\n{entry.body}\n"


def write_entry(entry: MemoryEntry, directory: Path) -> Path:
    """Write a new memory entry to ``directory``.

    Assigns the next available sequence number, generates a filename
    slug from the title, writes the file, and returns its path.
    """
    directory.mkdir(parents=True, exist_ok=True)
    seq = _next_sequence_number(directory)
    slug = _slugify(entry.title)
    filename = f"{seq:04d}-{slug}.md"
    path = directory / filename
    path.write_text(_render_entry(entry), "utf-8")
    return path


def update_entry(entry: MemoryEntry) -> None:
    """Write an entry back to its existing ``file_path``."""
    if entry.file_path is None:
        raise ValueError("entry has no file_path; use write_entry for new entries")
    entry.file_path.write_text(_render_entry(entry), "utf-8")


def write_index(index: MemoryIndex, directory: Path) -> Path:
    """Write ``_index.md`` in ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    meta = {
        "type": "index",
        "covers": index.covers,
        "token_count": index.token_count,
        "last_generated": index.last_generated,
    }
    fm = yaml.dump(meta, default_flow_style=None, sort_keys=False, allow_unicode=False).rstrip("\n")
    text = f"---\n{fm}\n---\n\n{index.body}\n"
    path = directory / "_index.md"
    path.write_text(text, "utf-8")
    return path
