# Parse memory entry markdown files into MemoryEntry / MemoryIndex.

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import yaml

from .types import MemoryEntry


def _stringify_ts(value: object) -> str:
    """Normalize a parsed YAML value to an ISO 8601 string.

    pyyaml auto-parses ISO timestamps into datetime/date objects. We need
    them back as strings in their original shape.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        s = value.isoformat()
        return s.replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


class ParseError(Exception):
    """Raised when a memory file cannot be parsed."""


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown file into YAML frontmatter dict and remaining body.

    Raises ParseError if the file does not start with a ``---`` fence.
    """
    stripped = text.lstrip("\n")
    if not stripped.startswith("---"):
        raise ParseError("missing YAML frontmatter (no opening ---)")

    rest = stripped[3:]
    m = re.search(r"^---\s*$", rest, re.MULTILINE)
    if m is None:
        raise ParseError("missing YAML frontmatter (no closing ---)")

    yaml_text = rest[: m.start()]
    after = rest[m.end():]
    meta = yaml.safe_load(yaml_text)
    if not isinstance(meta, dict):
        raise ParseError("YAML frontmatter is not a mapping")
    return meta, after.lstrip("\n")


_REQUIRED_FIELDS = ("title", "type")


def parse_entry(path: Path) -> MemoryEntry:
    """Parse a memory entry markdown file into a ``MemoryEntry``.

    Raises ``ParseError`` on malformed files or missing required fields.
    """
    text = path.read_text("utf-8")
    meta, body = _split_frontmatter(text)

    missing = [f for f in _REQUIRED_FIELDS if f not in meta]
    if missing:
        raise ParseError(f"missing required frontmatter fields: {', '.join(missing)}")

    related = meta.get("related") or []
    if not isinstance(related, list):
        related = [str(related)]

    return MemoryEntry(
        title=str(meta["title"]),
        type=meta["type"],
        body=body.strip(),
        created=_stringify_ts(meta.get("created")),
        modified=_stringify_ts(meta.get("modified")),
        related=[str(r) for r in related],
        file_path=path,
    )
