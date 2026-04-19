# Artifact listing for run directory.
# Scans run root .md files and stories/ recursively, excluding subagents/.

from __future__ import annotations

import os
from pathlib import Path


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
                })

    return results
