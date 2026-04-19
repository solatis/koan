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
    type: MemoryType
    body: str
    created: str = ""        # ISO 8601 timestamp; set automatically on write
    modified: str = ""       # ISO 8601 timestamp; set automatically on write
    related: list[str] = field(default_factory=list)
    file_path: Path | None = None
