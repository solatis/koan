# Parse memory entry markdown files into MemoryEntry / MemoryIndex.

from __future__ import annotations

import re
from pathlib import Path

import yaml

from .types import MemoryEntry, MemoryIndex


class ParseError(Exception):
    """Raised when a memory file cannot be parsed."""


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown file into YAML frontmatter dict and remaining text.

    Raises ParseError if the file does not start with a ``---`` fence.
    """
    stripped = text.lstrip("\n")
    if not stripped.startswith("---"):
        raise ParseError("missing YAML frontmatter (no opening ---)")

    # Find closing ---
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


def _split_intro_body(text: str) -> tuple[str, str]:
    """Separate contextual introduction (first paragraph) from body.

    The introduction ends at the first ``## `` heading or the first
    blank-line-delimited paragraph break.
    """
    # If text starts with a heading, there is no introduction.
    if re.match(r"^##\s", text):
        return "", text

    # Split at first heading.
    heading_match = re.search(r"^##\s", text, re.MULTILINE)
    if heading_match:
        before = text[: heading_match.start()].rstrip()
        after = text[heading_match.start():]
        # Introduction is the first paragraph of `before`.
        parts = re.split(r"\n\n+", before, maxsplit=1)
        intro = parts[0].strip()
        remaining = parts[1].strip() if len(parts) > 1 else ""
        body = (remaining + "\n\n" + after).strip() if remaining else after.strip()
        return intro, body

    # No heading -- split on double newline.
    parts = re.split(r"\n\n+", text, maxsplit=1)
    intro = parts[0].strip()
    body = parts[1].strip() if len(parts) > 1 else ""
    return intro, body


_REQUIRED_FIELDS = ("title", "type", "date", "source", "status")


def parse_entry(path: Path) -> MemoryEntry:
    """Parse a memory entry markdown file into a ``MemoryEntry``.

    Raises ``ParseError`` on malformed files or missing required fields.
    """
    text = path.read_text("utf-8")
    meta, after = _split_frontmatter(text)

    missing = [f for f in _REQUIRED_FIELDS if f not in meta]
    if missing:
        raise ParseError(f"missing required frontmatter fields: {', '.join(missing)}")

    intro, body = _split_intro_body(after)
    if not intro:
        raise ParseError("missing contextual introduction")
    if not body:
        raise ParseError("missing body")

    tags = meta.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]

    supersedes = meta.get("supersedes")
    if supersedes is not None:
        supersedes = str(supersedes)
        if supersedes.lower() == "null":
            supersedes = None

    related = meta.get("related") or []
    if not isinstance(related, list):
        related = [str(related)]

    return MemoryEntry(
        title=str(meta["title"]),
        type=meta["type"],
        date=str(meta["date"]),
        source=meta["source"],
        status=meta["status"],
        contextual_introduction=intro,
        body=body,
        tags=[str(t) for t in tags],
        supersedes=supersedes,
        related=[str(r) for r in related],
        file_path=path,
    )


def parse_index(path: Path) -> MemoryIndex:
    """Parse a ``_index.md`` file into a ``MemoryIndex``."""
    text = path.read_text("utf-8")
    meta, after = _split_frontmatter(text)

    covers = meta.get("covers", [])
    if not isinstance(covers, list):
        covers = []
    covers = [int(c) for c in covers]

    return MemoryIndex(
        covers=covers,
        token_count=int(meta.get("token_count", 0)),
        last_generated=str(meta.get("last_generated", "")),
        body=after.strip(),
        file_path=path,
    )
