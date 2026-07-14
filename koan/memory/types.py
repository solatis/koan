# Data model for memory entries.

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

MemoryType = Literal["decision", "context", "lesson", "procedure"]

MEMORY_TYPES: tuple[MemoryType, ...] = (
    "decision", "context", "lesson", "procedure",
)


@dataclass
class MemoryEntry:
    title: str
    # Deliberately `str`, not MemoryType: MemoryEntry is a pre-validation
    # container (entries arrive from disk and tool input with arbitrary type
    # strings); validate_entry is the gate that enforces the MemoryType
    # vocabulary. A Literal here would reject exactly the invalid entries the
    # validation path exists to report on.
    type: str
    body: str
    created: str = ""        # ISO 8601 timestamp; set automatically on write
    modified: str = ""       # ISO 8601 timestamp; set automatically on write
    related: list[str] = field(default_factory=list)
    file_path: Path | None = None
