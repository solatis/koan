# On-disk state I/O for run state files.
# All JSON writes use atomic tmp+rename to prevent partial reads.
# Story state I/O (load/save_story_state, load_all_story_states, discover_story_ids)
# deleted in M1: the legacy "execution" phase that used them is removed.

from __future__ import annotations

import json
import os
from pathlib import Path

import aiofiles

from .logger import get_logger

log = get_logger("run_state")


async def atomic_write_json(path: str | Path, value: object) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    async with aiofiles.open(tmp, "w") as f:
        await f.write(json.dumps(value, indent=2))
    os.rename(tmp, p)
    try:
        size = p.stat().st_size
    except OSError:
        size = -1
    log.debug("atomic_write_json: path=%s bytes=%d", p, size)


async def load_run_state(run_dir: str | Path) -> dict:
    p = Path(run_dir) / "run-state.json"
    try:
        async with aiofiles.open(p, "r") as f:
            data = json.loads(await f.read())
        log.debug("load_run_state: path=%s", p)
        return data
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        log.warning("load_run_state failed for %s: %s", p, exc)
        return {}


async def save_run_state(run_dir: str | Path, state: dict) -> None:
    await atomic_write_json(Path(run_dir) / "run-state.json", state)


async def ensure_subagent_directory(
    run_dir: str | Path, label: str
) -> str:
    d = Path(run_dir) / "subagents" / label
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


