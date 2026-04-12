# Data model for memory entries and indexes.

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

MemoryType = Literal["decision", "context", "lesson", "procedure", "milestone"]
MemorySource = Literal["user-stated", "llm-inferred", "post-mortem"]
MemoryStatus = Literal["active", "review-needed", "deprecated", "archived"]

MEMORY_TYPES: tuple[MemoryType, ...] = (
    "decision", "context", "lesson", "procedure", "milestone",
)
MEMORY_SOURCES: tuple[MemorySource, ...] = (
    "user-stated", "llm-inferred", "post-mortem",
)
MEMORY_STATUSES: tuple[MemoryStatus, ...] = (
    "active", "review-needed", "deprecated", "archived",
)

# Directory name for each memory type.
TYPE_DIRS: dict[MemoryType, str] = {
    "decision": "decisions",
    "context": "context",
    "lesson": "lessons",
    "procedure": "procedures",
    "milestone": "milestones",
}


@dataclass
class MemoryEntry:
    title: str
    type: MemoryType
    date: str
    source: MemorySource
    status: MemoryStatus
    contextual_introduction: str
    body: str
    tags: list[str] = field(default_factory=list)
    supersedes: str | None = None
    related: list[str] = field(default_factory=list)
    file_path: Path | None = None


@dataclass
class MemoryIndex:
    covers: list[int] = field(default_factory=list)
    token_count: int = 0
    last_generated: str = ""
    body: str = ""
    file_path: Path | None = None
