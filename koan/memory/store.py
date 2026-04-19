# High-level operations over the flat .koan/memory/ directory.

from __future__ import annotations

import re
from pathlib import Path

from ..logger import get_logger
from .types import MemoryEntry, MemoryType
from .parser import parse_entry
from .writer import write_entry as _write_entry, update_entry as _update_entry

log = get_logger("memory.store")

_ENTRY_PATTERN = re.compile(r"^(\d{4})-.*\.md$")


class MemoryStore:
    """File-backed store for koan memory entries in a flat directory."""

    def __init__(self, project_root: str | Path) -> None:
        self._root = Path(project_root)
        self._memory_dir = self._root / ".koan" / "memory"

    # -- Directory management ---------------------------------------------------

    def init(self) -> None:
        """Create the memory directory if it doesn't exist."""
        log.debug("init memory_dir=%s", self._memory_dir)
        self._memory_dir.mkdir(parents=True, exist_ok=True)

    # -- Query ------------------------------------------------------------------

    def _iter_entry_paths(self) -> list[Path]:
        """Return all NNNN-*.md paths in the memory directory, sorted by name."""
        if not self._memory_dir.is_dir():
            return []
        return sorted(
            p for p in self._memory_dir.iterdir()
            if p.is_file() and _ENTRY_PATTERN.match(p.name)
        )

    def list_entries(self, type: MemoryType | None = None) -> list[MemoryEntry]:
        """List entries, optionally filtered by type. Sorted by sequence number."""
        paths = self._iter_entry_paths()
        log.debug("list_entries type=%s found %d file(s)", type or "*", len(paths))
        entries = [parse_entry(p) for p in paths]
        if type is not None:
            entries = [e for e in entries if e.type == type]
            log.debug("list_entries filtered to %d entry/entries of type '%s'", len(entries), type)
        return entries

    def get_entry(self, number: int) -> MemoryEntry | None:
        """Find and parse a specific entry by global sequence number."""
        if not self._memory_dir.is_dir():
            log.debug("get_entry(%d) memory_dir does not exist", number)
            return None
        prefix = f"{number:04d}-"
        for p in self._memory_dir.iterdir():
            if p.is_file() and p.name.startswith(prefix) and p.name.endswith(".md"):
                entry = parse_entry(p)
                log.debug("get_entry(%d) found %s type=%s", number, p.name, entry.type)
                return entry
        log.debug("get_entry(%d) not found", number)
        return None

    def entry_count(self, type: MemoryType | None = None) -> int:
        """Count entries, optionally filtered by type."""
        paths = self._iter_entry_paths()
        if type is None:
            return len(paths)
        return sum(1 for p in paths if parse_entry(p).type == type)

    # -- Mutations --------------------------------------------------------------

    def add_entry(
        self,
        type: MemoryType,
        title: str,
        body: str,
        related: list[str] | None = None,
    ) -> MemoryEntry:
        """Create a new entry, write it to disk, return with file_path set."""
        log.info("add_entry type=%s title=%r body_len=%d related=%s", type, title, len(body), related or [])
        entry = MemoryEntry(
            title=title,
            type=type,
            body=body,
            related=related or [],
        )
        path = _write_entry(entry, self._memory_dir)
        entry.file_path = path
        log.info("add_entry written -> %s", path.name)
        return entry

    def update_entry(self, entry: MemoryEntry) -> None:
        """Write an entry back to its existing file_path."""
        log.info("update_entry id=%s type=%s title=%r", entry.file_path.name if entry.file_path else "?", entry.type, entry.title)
        _update_entry(entry)
        log.debug("update_entry written -> %s", entry.file_path)

    def forget_entry(self, entry: MemoryEntry) -> None:
        """Delete an entry file from disk. Git preserves history."""
        if entry.file_path is None:
            raise ValueError("entry has no file_path")
        log.info("forget_entry %s type=%s title=%r", entry.file_path.name, entry.type, entry.title)
        entry.file_path.unlink()
        log.debug("forget_entry deleted %s", entry.file_path)

    # -- Summary ----------------------------------------------------------------

    def get_summary(self) -> str | None:
        """Return the content of summary.md if it exists."""
        p = self._memory_dir / "summary.md"
        if p.is_file():
            text = p.read_text("utf-8")
            log.debug("get_summary loaded %d chars from %s", len(text), p)
            return text
        log.debug("get_summary no summary.md found")
        return None

    def summary_is_stale(self) -> bool:
        """True if summary.md is missing or older than any entry file."""
        summary_path = self._memory_dir / "summary.md"
        if not summary_path.is_file():
            return self.entry_count() > 0
        summary_mtime = summary_path.stat().st_mtime
        for e in self.list_entries():
            if e.file_path is None:
                continue
            if e.file_path.stat().st_mtime > summary_mtime:
                return True
        return False

    async def regenerate_summary(self, project_name: str = "") -> None:
        """Regenerate summary.md from all current entries."""
        log.info("regenerate_summary starting (project_name=%r, entry_count=%d)", project_name, self.entry_count())
        from .summarize import regenerate_summary

        await regenerate_summary(self, project_name=project_name)
        log.info("regenerate_summary complete")
