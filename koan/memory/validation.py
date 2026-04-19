# Validate that a MemoryEntry conforms to the spec.

from __future__ import annotations

from .types import MEMORY_TYPES, MemoryEntry


def validate_entry(entry: MemoryEntry) -> list[str]:
    """Return a list of validation errors (empty = valid)."""
    errors: list[str] = []

    if not entry.title:
        errors.append("title is required")

    if not entry.type:
        errors.append("type is required")
    elif entry.type not in MEMORY_TYPES:
        errors.append(f"invalid type: {entry.type}")

    if not entry.body:
        errors.append("body is required")

    return errors
