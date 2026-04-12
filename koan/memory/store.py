# High-level operations over the .koan/memory/ directory tree.

from __future__ import annotations

import re
from pathlib import Path

from .types import (
    TYPE_DIRS,
    MemoryEntry,
    MemoryIndex,
    MemorySource,
    MemoryStatus,
    MemoryType,
)
from .parser import parse_entry, parse_index
from .writer import write_entry as _write_entry, update_entry as _update_entry


class MemoryStore:
    """File-backed store for koan memory entries."""

    def __init__(self, project_root: str | Path) -> None:
        self._root = Path(project_root)
        self._memory_dir = self._root / ".koan" / "memory"
        self._user_dir = self._root / ".koan" / "user"

    # -- Directory management ---------------------------------------------------

    def init(self) -> None:
        """Create the directory structure if it doesn't exist."""
        for dir_name in TYPE_DIRS.values():
            (self._memory_dir / dir_name).mkdir(parents=True, exist_ok=True)
        self._user_dir.mkdir(parents=True, exist_ok=True)

    def _type_dir(self, t: MemoryType) -> Path:
        return self._memory_dir / TYPE_DIRS[t]

    # -- Query ------------------------------------------------------------------

    def list_entries(self, type: MemoryType | None = None) -> list[MemoryEntry]:
        """List entries, optionally filtered by type. Sorted by sequence number."""
        types = [type] if type is not None else list(TYPE_DIRS.keys())
        entries: list[MemoryEntry] = []
        pattern = re.compile(r"^(\d{4})-.*\.md$")
        for t in types:
            d = self._type_dir(t)
            if not d.is_dir():
                continue
            for p in sorted(d.iterdir()):
                if pattern.match(p.name):
                    entries.append(parse_entry(p))
        return entries

    def get_entry(self, type: MemoryType, number: int) -> MemoryEntry | None:
        """Find and parse a specific entry by type and sequence number."""
        d = self._type_dir(type)
        if not d.is_dir():
            return None
        prefix = f"{number:04d}-"
        for p in d.iterdir():
            if p.name.startswith(prefix) and p.name.endswith(".md"):
                return parse_entry(p)
        return None

    def entry_count(self, type: MemoryType | None = None) -> int:
        """Count entries, optionally filtered by type."""
        types = [type] if type is not None else list(TYPE_DIRS.keys())
        pattern = re.compile(r"^\d{4}-.*\.md$")
        count = 0
        for t in types:
            d = self._type_dir(t)
            if not d.is_dir():
                continue
            count += sum(1 for p in d.iterdir() if pattern.match(p.name))
        return count

    # -- Mutations --------------------------------------------------------------

    def add_entry(
        self,
        type: MemoryType,
        title: str,
        date: str,
        source: MemorySource,
        contextual_introduction: str,
        body: str,
        status: MemoryStatus = "active",
        tags: list[str] | None = None,
        supersedes: str | None = None,
        related: list[str] | None = None,
    ) -> MemoryEntry:
        """Create a new entry, write it to disk, return with file_path set."""
        entry = MemoryEntry(
            title=title,
            type=type,
            date=date,
            source=source,
            status=status,
            contextual_introduction=contextual_introduction,
            body=body,
            tags=tags or [],
            supersedes=supersedes,
            related=related or [],
        )
        d = self._type_dir(type)
        path = _write_entry(entry, d)
        entry.file_path = path
        return entry

    def update_entry(self, entry: MemoryEntry) -> None:
        """Write an entry back to its existing file_path."""
        _update_entry(entry)

    def deprecate_entry(self, entry: MemoryEntry) -> None:
        """Set status to 'deprecated' and write back."""
        entry.status = "deprecated"
        _update_entry(entry)

    # -- Summaries / indexes ----------------------------------------------------

    def get_summary(self) -> str | None:
        """Return the content of summary.md if it exists."""
        p = self._memory_dir / "summary.md"
        if p.is_file():
            return p.read_text("utf-8")
        return None

    def get_index(self, type: MemoryType) -> MemoryIndex | None:
        """Return the parsed _index.md for the given type, if it exists."""
        p = self._type_dir(type) / "_index.md"
        if p.is_file():
            return parse_index(p)
        return None
