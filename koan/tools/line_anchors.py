# Stateless hash-anchored line protocol.
#
# Shared by the untrusted filesystem tools (read/edit) and the trusted artifact
# tools (koan_artifact_read/koan_artifact_edit). See docs/tools.md for the full
# strategy and rationale.
#
# An anchor is a content-derived, per-line handle the read hands back and the
# edit references -- replacing exact-string-match. It carries both a LOCATION
# (the hash) and, inline, the VERIFICATION content (the line text), so an edit
# resolves to a precise line and detects drift since the read. The scheme is
# stateless: anchors are recomputed from the file at edit time, never stored.

from __future__ import annotations

import re

# Separates the anchor from the line content in read output and edit tokens.
# U+00A7 (section sign): never appears in an 8-hex anchor, rare in source lines.
ANCHOR_DELIMITER = "§"

# Anchor grammar: 8 lowercase hex chars, optional "~N" ordinal for collisions.
_ANCHOR_RE = re.compile(r"^[0-9a-f]{8}(?:~\d+)?$")

_FNV32_OFFSET = 0x811C9DC5
_FNV32_PRIME = 0x01000193
_FNV32_MASK = 0xFFFFFFFF


def fnv1a32(text: str) -> str:
    """Return the 8-char hex FNV-1a 32-bit hash of *text*.

    Pure, fast, dependency-free. Matches dirac's contentHash so the anchor
    scheme is portable. Hashes Unicode code points (ASCII/BMP identical to
    dirac's UTF-16 charCodeAt path; the distinction is irrelevant since koan
    only needs internal consistency).
    """
    h = _FNV32_OFFSET
    for ch in text:
        h = ((h ^ ord(ch)) * _FNV32_PRIME) & _FNV32_MASK
    return format(h, "08x")


def compute_anchors(lines: list[str]) -> list[str]:
    """Return one unique anchor per line, disambiguating hash collisions by ordinal.

    A line's anchor is fnv1a32(line). When several lines share a hash (blank
    lines, repeated `}`), the 2nd, 3rd, ... occurrences in file order get a
    `~N` suffix so every anchor in the file is unique. Pure function of *lines*.

    Anchors MUST be computed over the whole file (not a read slice) so that a
    read's anchors and an edit's recomputed anchors agree.
    """
    counts: dict[str, int] = {}
    anchors: list[str] = []
    for line in lines:
        base = fnv1a32(line)
        n = counts.get(base, 0) + 1
        counts[base] = n
        anchors.append(base if n == 1 else f"{base}~{n}")
    return anchors


def render_anchored(content: str, offset: int = 0, limit: int | None = None) -> str:
    """Format *content* lines [offset : offset+limit] as `{lineno}\\t{anchor}{ANCHOR_DELIMITER}{line}`.

    Line numbers are 1-based absolute (honouring offset). Anchors are computed
    over the whole *content* so they remain resolvable by an edit, then only the
    requested window is emitted. Matches the cat -n line count (splitlines drops
    the trailing empty segment after a final newline).
    """
    lines = content.splitlines()
    anchors = compute_anchors(lines)
    end = len(lines) if limit is None else min(offset + limit, len(lines))
    rows = [
        f"{i + 1}\t{anchors[i]}{ANCHOR_DELIMITER}{lines[i]}"
        for i in range(max(offset, 0), end)
    ]
    return "\n".join(rows)


def _resolve_anchor(token: str, lines: list[str], anchors: list[str]) -> tuple[int, str | None]:
    """Resolve an anchor token to a line index, verifying inline content.

    *token* is `{anchor}` or `{anchor}{ANCHOR_DELIMITER}{line}` as copied from a
    read. Returns (index, None) on success or (-1, error_message). When the token
    carries the inline content, it is verified against the current line so a file
    that drifted since the read fails loudly instead of editing the wrong place.
    """
    if not token or not token.strip():
        return -1, "anchor is missing"
    name, sep, provided = token.partition(ANCHOR_DELIMITER)
    name = name.strip()
    if not _ANCHOR_RE.match(name):
        return -1, (
            f"anchor {name!r} is malformed; expected an 8-hex anchor copied from a "
            f"read, e.g. 'a1f3c2d8{ANCHOR_DELIMITER}<line text>'"
        )
    try:
        idx = anchors.index(name)
    except ValueError:
        return -1, (
            f"anchor {name!r} not found in the file; re-read it to get current anchors"
        )
    if sep and provided != lines[idx]:
        return -1, (
            f"anchor {name!r} content mismatch -- the file changed since the read. "
            f"Expected {lines[idx]!r}, got {provided!r}. Re-read the file."
        )
    return idx, None


def apply_anchored_edit(
    content: str,
    anchor: str,
    text: str,
    end_anchor: str | None = None,
    edit_type: str = "replace",
) -> tuple[str | None, str | None]:
    """Apply one anchored edit to *content*. Pure function.

    Returns (new_content, None) on success or (None, error_message). Shared by
    edit_tool and artifact_edit_core so both tools edit identically.

    edit_type:
      - "replace": replace the anchored line, or the inclusive range
        [anchor, end_anchor] when end_anchor is given. Empty *text* deletes.
      - "insert_before" / "insert_after": insert *text* relative to the anchored
        line (end_anchor must be absent).

    *text* is split on "\\n" into the inserted/replacement lines; an empty *text*
    contributes no lines (so a replace with empty text deletes the target line).
    """
    if edit_type not in ("replace", "insert_before", "insert_after"):
        return None, f"unknown edit_type {edit_type!r}"
    if end_anchor and edit_type != "replace":
        return None, f"end_anchor is only valid with edit_type='replace', not {edit_type!r}"

    had_trailing_newline = content.endswith("\n")
    lines = content.splitlines()
    anchors = compute_anchors(lines)

    idx, err = _resolve_anchor(anchor, lines, anchors)
    if err:
        return None, err

    segment = text.split("\n") if text else []

    if edit_type == "insert_before":
        new_lines = lines[:idx] + segment + lines[idx:]
    elif edit_type == "insert_after":
        new_lines = lines[: idx + 1] + segment + lines[idx + 1:]
    else:  # replace
        end_idx = idx
        if end_anchor:
            end_idx, err = _resolve_anchor(end_anchor, lines, anchors)
            if err:
                return None, err
            if end_idx < idx:
                return None, "end_anchor must refer to a line at or after anchor"
        new_lines = lines[:idx] + segment + lines[end_idx + 1:]

    new_content = "\n".join(new_lines)
    if had_trailing_newline:
        new_content += "\n"
    return new_content, None
