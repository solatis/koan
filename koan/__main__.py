# Entry point: `uv run koan` or `python -m koan`.
# Loads config, builds AppState, starts the Starlette server on 127.0.0.1.
#
# In a development checkout (frontend/ directory exists next to the koan
# package), the entry point automatically rebuilds the Vite bundle into
# koan/web/static/app/ when frontend sources are newer than the last build.
# In an installed wheel the frontend/ directory is absent and the check is
# a no-op — the pre-built assets ship inside the wheel.

from __future__ import annotations

import argparse
import asyncio
import logging
import socket
import subprocess
import sys
from pathlib import Path

import uvicorn

from .config import load_koan_config
from .logger import setup_logging
from .state import AppState
from .web.app import FRONTEND_DIST, create_app

log = logging.getLogger(__name__)

# Resolve relative to the *repository root* (one level above the koan package).
# Only present in a development checkout — absent in an installed wheel.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_FRONTEND_SRC = _REPO_ROOT / "frontend" / "src"


def _frontend_needs_rebuild() -> bool:
    """True when frontend sources are newer than the last Vite build."""
    if not _FRONTEND_SRC.is_dir():
        return False  # not a dev checkout

    build_marker = FRONTEND_DIST / "index.html"
    if not build_marker.exists():
        return True  # never built

    build_mtime = build_marker.stat().st_mtime
    return any(
        p.stat().st_mtime > build_mtime
        for p in _FRONTEND_SRC.rglob("*")
        if p.is_file()
    )


def _rebuild_frontend() -> None:
    """Run ``npm run build`` in the frontend directory."""
    frontend_dir = _FRONTEND_SRC.parent
    log.info("Frontend sources changed — rebuilding…")
    try:
        subprocess.run(
            ["npm", "run", "build"],
            cwd=str(frontend_dir),
            check=True,
            capture_output=True,
            text=True,
        )
        log.info("Frontend build complete.")
    except FileNotFoundError:
        log.warning("npm not found — skipping frontend rebuild.")
    except subprocess.CalledProcessError as exc:
        log.error("Frontend build failed:\n%s", exc.stderr)
        sys.exit(1)


def _find_free_port() -> int:
    """Bind to port 0 and let the OS assign a free ephemeral port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    parser = argparse.ArgumentParser(prog="koan")
    parser.add_argument("--port", type=int, default=None,
                        help="Port to listen on (default: random free port)")
    parser.add_argument("--log-level", type=str, default="INFO")
    parser.add_argument("--no-open", action="store_true", help="Don't open browser on startup")
    parser.add_argument("--skip-build", action="store_true", help="Skip frontend rebuild check")
    parser.add_argument("-p", "--prompt", type=str, default="",
                        help="Pre-fill the task description")
    parser.add_argument("--yolo", action="store_true",
                        help="Skip all agent permission prompts (dangerous)")
    args = parser.parse_args()

    setup_logging(args.log_level)

    if not args.skip_build and _frontend_needs_rebuild():
        _rebuild_frontend()

    port = args.port if args.port is not None else _find_free_port()

    config = asyncio.run(load_koan_config())
    app_state = AppState(config=config, port=port, open_browser=not args.no_open,
                          initial_prompt=args.prompt, yolo=args.yolo)
    app = create_app(app_state)

    host = "127.0.0.1"
    # timeout_graceful_shutdown=0: don't wait for HTTP clients to disconnect.
    # Agent cleanup happens in the lifespan shutdown handler instead.
    uvicorn.run(app, host=host, port=port, log_level=args.log_level.lower(),
                timeout_graceful_shutdown=0)


if __name__ == "__main__":
    main()
