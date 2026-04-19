# Pure CRUD and validation operations over MemoryStore.
# No MCP or web dependencies -- safe to import from CLI handlers.

from __future__ import annotations

import logging

from .store import MemoryStore
from .types import MEMORY_TYPES

log = logging.getLogger(__name__)


class EntryNotFoundError(ValueError):
    """Raised when a requested entry_id does not exist."""


class TypeMismatchError(ValueError):
    """Raised when the found entry's type does not match the requested type."""


def validate_memory_type(type_str: str) -> None:
    """Raise ValueError if type_str is not a valid memory type."""
    if type_str not in MEMORY_TYPES:
        raise ValueError(
            f"'{type_str}' is not a valid memory type. "
            f"Valid types: {list(MEMORY_TYPES)}"
        )


def entry_id_from_path(path_name: str) -> int | None:
    """Extract NNNN sequence number from 'NNNN-slug.md'."""
    if len(path_name) < 5 or path_name[4] != "-":
        return None
    try:
        return int(path_name[:4])
    except ValueError:
        return None


def memorize(
    store: MemoryStore,
    type: str,
    title: str,
    body: str,
    related: list[str] | None = None,
    entry_id: int | None = None,
) -> dict:
    """Create or update a memory entry. Raises ValueError on validation errors."""
    validate_memory_type(type)

    if entry_id is None:
        log.info("memorize CREATE type=%s title=%r body_len=%d", type, title, len(body))
        entry = store.add_entry(
            type=type,  # type: ignore[arg-type]
            title=title,
            body=body,
            related=related or [],
        )
        new_id = entry_id_from_path(entry.file_path.name) if entry.file_path else None
        log.info("memorize CREATED entry_id=%s file=%s", new_id, entry.file_path.name if entry.file_path else "?")
        return {
            "op": "created",
            "type": type,
            "entry_id": new_id,
            "file_path": str(entry.file_path) if entry.file_path else None,
            "created": entry.created,
            "modified": entry.modified,
        }
    else:
        log.info("memorize UPDATE entry_id=%d type=%s title=%r", entry_id, type, title)
        existing = store.get_entry(entry_id)
        if existing is None:
            raise EntryNotFoundError(f"No entry with id {entry_id}")
        if existing.type != type:
            raise TypeMismatchError(
                f"Entry {entry_id} has type '{existing.type}', not '{type}'"
            )
        existing.title = title
        existing.body = body
        if related is not None:
            existing.related = related
        store.update_entry(existing)
        log.info("memorize UPDATED entry_id=%d file=%s", entry_id, existing.file_path.name if existing.file_path else "?")
        return {
            "op": "updated",
            "type": type,
            "entry_id": entry_id,
            "file_path": str(existing.file_path) if existing.file_path else None,
            "created": existing.created,
            "modified": existing.modified,
        }


def forget(
    store: MemoryStore,
    entry_id: int,
    type: str | None = None,
) -> dict:
    """Delete a memory entry. Raises ValueError on validation or lookup errors."""
    if type is not None:
        validate_memory_type(type)

    log.info("forget entry_id=%d type=%s", entry_id, type or "*")
    existing = store.get_entry(entry_id)
    if existing is None:
        raise EntryNotFoundError(f"No entry with id {entry_id}")
    if type is not None and existing.type != type:
        raise TypeMismatchError(
            f"Entry {entry_id} has type '{existing.type}', not '{type}'"
        )
    path_str = str(existing.file_path) if existing.file_path else None
    log.info(
        "forget DELETING %s type=%s title=%r",
        existing.file_path.name if existing.file_path else "?",
        existing.type,
        existing.title,
    )
    store.forget_entry(existing)
    log.info("forget DELETED entry_id=%d", entry_id)
    return {
        "op": "forgotten",
        "type": existing.type,
        "entry_id": entry_id,
        "file_path": path_str,
    }


async def status(
    store: MemoryStore,
    type: str | None = None,
    regenerate: bool = True,
) -> dict:
    """Return summary and entry listing. Regenerates stale summary when possible."""
    if type is not None:
        validate_memory_type(type)

    log.info("status type=%s", type or "*")

    regenerated = False
    regen_error: str | None = None

    if regenerate and store.summary_is_stale():
        log.info("status regenerating stale summary")
        try:
            await store.regenerate_summary()
            regenerated = True
            log.info("status summary regenerated")
        except Exception:
            log.exception("status summary regeneration failed")
            regen_error = "Summary regeneration failed -- see server logs."

    summary = store.get_summary() or ""
    entries = store.list_entries(type=type)  # type: ignore[arg-type]
    out_entries = [
        {
            "entry_id": (
                entry_id_from_path(e.file_path.name)
                if e.file_path else None
            ),
            "title": e.title,
            "type": e.type,
            "created": e.created,
            "modified": e.modified,
        }
        for e in entries
    ]
    log.info(
        "status returning %d entries, summary_len=%d, regenerated=%s",
        len(out_entries), len(summary), regenerated,
    )

    result: dict = {
        "summary": summary,
        "entries": out_entries,
        "regenerated": regenerated,
    }
    if regen_error:
        result["error"] = regen_error
    return result
