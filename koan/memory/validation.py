# Validate that a MemoryEntry conforms to the spec.

from __future__ import annotations

import re

from .types import MEMORY_SOURCES, MEMORY_STATUSES, MEMORY_TYPES, MemoryEntry

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_entry(entry: MemoryEntry) -> list[str]:
    """Return a list of validation errors (empty = valid)."""
    errors: list[str] = []

    if not entry.title:
        errors.append("title is required")

    if not entry.type:
        errors.append("type is required")
    elif entry.type not in MEMORY_TYPES:
        errors.append(f"invalid type: {entry.type}")

    if not entry.date:
        errors.append("date is required")
    elif not _ISO_DATE.match(entry.date):
        errors.append(f"date is not a valid ISO 8601 date: {entry.date}")

    if not entry.source:
        errors.append("source is required")
    elif entry.source not in MEMORY_SOURCES:
        errors.append(f"invalid source: {entry.source}")

    if not entry.status:
        errors.append("status is required")
    elif entry.status not in MEMORY_STATUSES:
        errors.append(f"invalid status: {entry.status}")

    if not entry.contextual_introduction:
        errors.append("contextual_introduction is required")

    if not entry.body:
        errors.append("body is required")

    if entry.tags is not None:
        if not isinstance(entry.tags, list):
            errors.append("tags must be a list of strings")
        elif not all(isinstance(t, str) for t in entry.tags):
            errors.append("tags must be a list of strings")

    if entry.supersedes is not None and not isinstance(entry.supersedes, str):
        errors.append("supersedes must be a string path")

    if entry.related is not None:
        if not isinstance(entry.related, list):
            errors.append("related must be a list of string paths")
        elif not all(isinstance(r, str) for r in entry.related):
            errors.append("related must be a list of string paths")

    return errors
