# Upload storage primitives over a server-lifetime temporary directory.
# All I/O is isolated here; app.py and the route handler do all wiring.
# This module must NOT import from koan.web.app -- would create a cycle.

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import aiofiles
from mcp.types import ContentBlock, TextContent
from fastmcp.utilities.types import File, Image

from ..logger import get_logger
from ..state import UploadRecord, UploadState

log = get_logger("web.uploads")

_CHUNK = 64 * 1024  # 64 KiB streaming read chunk


def init_upload_state(state: UploadState) -> None:
    """Create the server-lifetime tempdir and assign it to state.tempdir.

    Idempotent: if tempdir is already set, returns immediately so the lifespan
    can call this unconditionally without risk of creating orphaned directories.
    """
    if state.tempdir is not None:
        return
    state.tempdir = tempfile.TemporaryDirectory()
    log.info("init_upload_state: tempdir=%s", state.tempdir.name)


def shutdown_upload_state(state: UploadState) -> None:
    """Cleanup the tempdir and clear in-memory entries.

    Called in the shutdown branch of the Starlette lifespan, after in-flight
    requests have finished, so entries discarded here are genuinely orphaned.
    Idempotent.
    """
    count = len(state.entries)
    if state.tempdir is not None:
        state.tempdir.cleanup()
        state.tempdir = None
    state.entries.clear()
    log.info("shutdown_upload_state: discarded %d entries", count)


async def register_upload(state: UploadState, upload_file) -> UploadRecord:
    """Stream a Starlette UploadFile into the tempdir and return its record.

    Generates a fresh uuid id, sanitizes the multipart filename to basename-
    only (blocks path traversal attempts), streams the file body in 64 KiB
    chunks to avoid pinning RAM for large uploads, then stores and returns
    the UploadRecord.
    """
    # Sanitize to basename only -- Path("../../etc/passwd").name == "passwd".
    raw_name = upload_file.filename or "unnamed"
    filename = Path(raw_name).name
    if not filename:
        raise ValueError("invalid filename")

    upload_id = uuid.uuid4().hex
    content_type = upload_file.content_type or "application/octet-stream"

    dest_dir = Path(state.tempdir.name) / upload_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename

    size = 0
    async with aiofiles.open(dest_path, "wb") as out:
        while True:
            chunk = upload_file.file.read(_CHUNK)
            if not chunk:
                break
            await out.write(chunk)
            size += len(chunk)

    record = UploadRecord(
        id=upload_id,
        filename=filename,
        size=size,
        content_type=content_type,
        path=dest_path,
        committed=False,
    )
    state.entries[upload_id] = record
    log.info("register_upload: id=%s filename=%s size=%d", upload_id, filename, size)
    return record


def resolve_upload(state: UploadState, upload_id: str) -> UploadRecord | None:
    """Return the UploadRecord for upload_id, or None on miss.

    Pure dict lookup -- never touches the filesystem.
    """
    return state.entries.get(upload_id)


def commit_to_run(
    state: UploadState,
    upload_ids: list[str],
    run_dir: str | Path,
) -> dict[str, Path]:
    """Move committed uploads from the tempdir into <run_dir>/uploads/<id>/.

    Uses os.rename for an atomic same-filesystem move. If tempdir and run_dir
    straddle filesystems, os.rename raises OSError -- the caller decides policy
    (this milestone propagates rather than silently falling back to shutil.move).

    Records are updated in place (path, committed=True) but never deleted, so
    later milestones can still look up filename/content_type after commit.

    Returns a dict mapping each successfully committed id to its new Path.
    Missing or already-committed ids are skipped silently (with a WARNING log).
    """
    run_dir = Path(run_dir)
    committed: dict[str, Path] = {}

    for uid in upload_ids:
        record = state.entries.get(uid)
        if record is None:
            log.warning("commit_to_run: unknown upload id=%s, skipping", uid)
            continue
        if record.committed:
            log.warning("commit_to_run: id=%s already committed, skipping", uid)
            continue

        dest_dir = run_dir / "uploads" / uid
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / record.filename

        os.rename(record.path, dest_path)

        # Remove the now-empty per-id directory from the tempdir.
        src_dir = record.path.parent
        try:
            src_dir.rmdir()
        except OSError:
            pass  # non-fatal if the directory is not empty or already removed

        record.path = dest_path
        record.committed = True
        committed[uid] = dest_path

    log.info("commit_to_run: moved %d file(s) to %s", len(committed), run_dir)
    return committed


def upload_ids_to_blocks(
    state: UploadState,
    run_dir: str | Path,
    upload_ids: list[str],
    runner_type: str,
) -> tuple[list[ContentBlock], list[dict]]:
    """Resolve upload IDs into MCP content blocks and an audit manifest.

    Files must already be committed to run_dir (endpoints commit on HTTP
    submission). Missing IDs are skipped with a WARNING log. For
    runner_type != "claude", the returned block list collapses to a single
    TextContent notice listing the attached filenames; the manifest is still
    populated regardless so the audit log records what the user attached.

    Returns (blocks, manifest) where manifest is a list of dicts with
    {upload_id, filename, size, content_type, path}.
    """
    records: list[UploadRecord] = []
    missing: list[str] = []

    for uid in upload_ids:
        rec = state.entries.get(uid)
        if rec is None:
            missing.append(uid)
        else:
            records.append(rec)

    if missing:
        log.warning(
            "upload_ids_to_blocks: %d unknown id(s): %s",
            len(missing), missing,
        )

    if not records:
        return [], []

    manifest: list[dict] = [
        {
            "upload_id": rec.id,
            "filename": rec.filename,
            "size": rec.size,
            "content_type": rec.content_type,
            "path": str(rec.path),
        }
        for rec in records
    ]

    # Claude receives actual file content; other runners get a text notice.
    # Keeping the manifest unconditional ensures the audit log always reflects
    # what the user attached, regardless of whether the runner consumed the bytes.
    if runner_type == "claude":
        blocks: list[ContentBlock] = []
        for rec in records:
            if rec.content_type.startswith("image/"):
                blocks.append(Image(path=str(rec.path)).to_image_content())
            else:
                blocks.append(File(path=str(rec.path)).to_resource_content())
    else:
        names = ", ".join(rec.filename for rec in records)
        blocks = [TextContent(
            type="text",
            text=(
                f"[{len(records)} attachment(s) omitted: file content blocks "
                f"are delivered only to Claude orchestrators. "
                f"Attached: {names}]"
            ),
        )]

    return blocks, manifest
