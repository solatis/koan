# Artifact listing and frontmatter management for run directory.
# Scans run root .md files and stories/ recursively, excluding subagents/.
#
# Frontmatter convention: YAML block delimited by '---' lines at file start.
# Driver-managed -- LLMs never see or write it; the helpers here read/write it.

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .logger import get_logger

log = get_logger("artifacts")

# -- Status taxonomy ----------------------------------------------------------

STATUS_VALUES: tuple[str, ...] = ("Draft", "Approved", "In-Progress", "Final")

_FRONTMATTER_DELIMITER = "---"


# -- Frontmatter helpers ------------------------------------------------------

def now_iso() -> str:
    """Return the current UTC time as ISO-8601 with 'Z' suffix."""
    return datetime.now(timezone.utc).isoformat()


def split_frontmatter(text: str) -> tuple[dict | None, str]:
    """Split a markdown text into (frontmatter_dict_or_None, body).

    Frontmatter convention: file starts with '---\\n', a YAML mapping follows,
    then a closing line equal to '---' (possibly with trailing whitespace).
    If the file does not start with '---', returns (None, text).
    If frontmatter is malformed (no closing delimiter or invalid YAML),
    returns (None, text) and logs a warning.
    """
    if not text.startswith(_FRONTMATTER_DELIMITER):
        return (None, text)

    # Skip the opening '---' line
    rest = text[len(_FRONTMATTER_DELIMITER):]
    if rest.startswith("\n"):
        rest = rest[1:]
    else:
        # Opening delimiter not followed by newline -- not valid frontmatter
        return (None, text)

    # Locate the closing '---' line (whole line, possibly trailing whitespace)
    lines = rest.split("\n")
    close_idx = None
    for i, line in enumerate(lines):
        if line.rstrip() == _FRONTMATTER_DELIMITER:
            close_idx = i
            break

    if close_idx is None:
        log.warning("frontmatter parse failed: no closing '---' delimiter")
        return (None, text)

    yaml_text = "\n".join(lines[:close_idx])
    body = "\n".join(lines[close_idx + 1:])

    try:
        meta = yaml.safe_load(yaml_text)
    except Exception as exc:
        log.warning("frontmatter parse failed: %s", exc)
        return (None, text)

    if not isinstance(meta, dict):
        log.warning("frontmatter parse failed: YAML is not a mapping")
        return (None, text)

    return (meta, body)


def dump_frontmatter(meta: dict) -> str:
    """Dump a frontmatter dict to its on-disk string form including delimiters.

    Returns '---\\n<yaml>---\\n'. Uses yaml.safe_dump with default_flow_style=False
    and sort_keys=False to keep field order stable.
    """
    # sort_keys=False preserves insertion order (status, created, last_modified)
    yaml_text = yaml.safe_dump(meta, default_flow_style=False, sort_keys=False)
    return f"{_FRONTMATTER_DELIMITER}\n{yaml_text}{_FRONTMATTER_DELIMITER}\n"


def compose_artifact(meta: dict, body: str) -> str:
    """Compose a frontmatter dict + body into the full on-disk text.

    If meta is empty or None, returns body unchanged.
    """
    if not meta:
        return body
    return dump_frontmatter(meta) + body


# -- Atomic write helper -------------------------------------------------------

def write_artifact_atomic(
    target: Path,
    body: str,
    status: str | None,
) -> dict:
    """Write `body` to `target` with managed YAML frontmatter, atomically.

    Reads the existing file (if any) to preserve `created`. Updates
    `last_modified` to now. Sets `status` if provided; otherwise preserves
    the existing status or defaults to 'In-Progress' for first writes.

    Validates `status` against STATUS_VALUES; raises ValueError on mismatch.
    Returns the resulting frontmatter dict.

    Atomic write via .tmp + os.rename avoids partial reads under concurrent access.
    """
    if status is not None and status not in STATUS_VALUES:
        raise ValueError(f"invalid status: {status!r}")

    existing_meta: dict = {}
    if target.exists():
        try:
            existing_text = target.read_text(encoding="utf-8")
            parsed_meta, _ = split_frontmatter(existing_text)
            if parsed_meta:
                existing_meta = parsed_meta
        except Exception as exc:
            # Treat unreadable existing file as if it had no frontmatter;
            # the write still proceeds so callers can recover from corrupt state.
            log.warning("could not read existing artifact %s: %s", target, exc)

    now = now_iso()
    new_meta = {
        # Explicit key order: status, created, last_modified
        "status": status if status is not None else existing_meta.get("status", "In-Progress"),
        "created": existing_meta.get("created", now),
        "last_modified": now,
    }

    final_text = compose_artifact(new_meta, body)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(final_text, encoding="utf-8")
    os.rename(tmp, target)

    return new_meta


# -- Status reading helper -----------------------------------------------------

def read_artifact_status(path: Path) -> str | None:
    """Read just enough of `path` to extract the frontmatter `status`.

    Returns None if the file has no frontmatter or no status field.
    Reads the first 4096 bytes; frontmatter is bounded by convention.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")[:4096]
    except Exception:
        return None
    meta, _ = split_frontmatter(text)
    if meta is None:
        return None
    return meta.get("status")


# -- Artifact listing ----------------------------------------------------------

def list_artifacts(run_dir: str | Path) -> list[dict]:
    root = Path(run_dir)
    results: list[dict] = []

    # Root-level .md files
    if root.is_dir():
        for f in sorted(root.iterdir()):
            if f.is_file() and f.suffix == ".md":
                st = f.stat()
                results.append({
                    "path": str(f.relative_to(root)),
                    "size": st.st_size,
                    "modified_at": st.st_mtime,
                    "status": read_artifact_status(f),
                })

    # stories/ recursively, excluding subagents/
    stories_dir = root / "stories"
    if stories_dir.is_dir():
        for dirpath, dirnames, filenames in os.walk(stories_dir):
            dirnames[:] = [d for d in dirnames if d != "subagents"]
            for fname in sorted(filenames):
                fp = Path(dirpath) / fname
                st = fp.stat()
                results.append({
                    "path": str(fp.relative_to(root)),
                    "size": st.st_size,
                    "modified_at": st.st_mtime,
                    "status": read_artifact_status(fp),
                })

    return results
