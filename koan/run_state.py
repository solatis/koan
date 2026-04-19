# On-disk state I/O for run and story state files.
# All JSON writes use atomic tmp+rename to prevent partial reads.

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


async def load_run_state(run_dir: str | Path) -> dict:
    p = Path(run_dir) / "run-state.json"
    try:
        async with aiofiles.open(p, "r") as f:
            return json.loads(await f.read())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        log.warning("load_run_state failed for %s: %s", p, exc)
        return {}


async def save_run_state(run_dir: str | Path, state: dict) -> None:
    await atomic_write_json(Path(run_dir) / "run-state.json", state)


async def load_story_state(run_dir: str | Path, story_id: str) -> dict:
    p = Path(run_dir) / "stories" / story_id / "state.json"
    try:
        async with aiofiles.open(p, "r") as f:
            return json.loads(await f.read())
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        log.warning("load_story_state failed for %s: %s", p, exc)
        return {}


async def save_story_state(
    run_dir: str | Path, story_id: str, updates: dict
) -> None:
    existing = await load_story_state(run_dir, story_id)
    merged = {**existing, **updates}
    await atomic_write_json(
        Path(run_dir) / "stories" / story_id / "state.json", merged
    )


async def load_all_story_states(run_dir: str | Path) -> list[dict]:
    run = await load_run_state(run_dir)
    story_ids = [s.get("id", s) if isinstance(s, dict) else s
                 for s in run.get("stories", [])]
    results = []
    for sid in story_ids:
        st = await load_story_state(run_dir, sid)
        if st:
            st.setdefault("storyId", sid)
            results.append(st)
    return results


async def ensure_subagent_directory(
    run_dir: str | Path, label: str
) -> str:
    d = Path(run_dir) / "subagents" / label
    d.mkdir(parents=True, exist_ok=True)
    return str(d)


async def discover_story_ids(run_dir: str | Path) -> list[str]:
    stories_dir = Path(run_dir) / "stories"
    if not stories_dir.is_dir():
        return []
    return sorted(
        d.name for d in stories_dir.iterdir() if d.is_dir()
    )
