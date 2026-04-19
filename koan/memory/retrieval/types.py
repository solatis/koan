from __future__ import annotations

from dataclasses import dataclass

from ..types import MemoryEntry


@dataclass
class SearchResult:
    entry: MemoryEntry
    entry_id: int
    score: float
