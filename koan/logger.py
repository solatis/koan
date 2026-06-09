# Logging setup for the koan server.
# Call setup_logging() once at startup; use get_logger(scope) everywhere else.

import logging
from pathlib import Path

_FORMAT = "%(asctime)s [%(name)s] %(levelname)s %(message)s"
_configured = False

# Payload truncation: cap user-input dumps so DEBUG logs stay scannable.
# A single constant makes the limit easy to tune without touching call sites.
MAX_PAYLOAD_CHARS: int = 2000

# Tracks the most recently attached per-run FileHandler so set_log_dir() can
# detach it before adding the new one. Necessary because the uvicorn process
# outlives individual runs; naive addHandler calls would fan out every log line
# to every prior run's file.
_run_file_handler: logging.FileHandler | None = None


def truncate_payload(s: str) -> str:
    """Truncate a user-input payload to MAX_PAYLOAD_CHARS with a length marker.

    Returns the original string when short enough; otherwise returns
    the first MAX_PAYLOAD_CHARS characters followed by
    '... [truncated N chars]' where N is the number of dropped chars.
    """
    if s is None:
        return ""
    if len(s) <= MAX_PAYLOAD_CHARS:
        return s
    dropped = len(s) - MAX_PAYLOAD_CHARS
    return f"{s[:MAX_PAYLOAD_CHARS]}... [truncated {dropped} chars]"


def setup_logging(level: str = "INFO") -> None:
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger("koan")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)


def set_log_dir(run_dir: str) -> None:
    # Detach the previous per-run handler before attaching the new one so each
    # run writes only to its own koan.log. The global tracks the most recently
    # attached handler; handlers from earlier runs are removed when the next run
    # starts, ensuring no log line fans out to a stale file.
    global _run_file_handler

    root = logging.getLogger("koan")
    log_path = Path(run_dir) / "koan.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(str(log_path))
    handler.setFormatter(logging.Formatter(_FORMAT))

    if _run_file_handler is not None:
        root.removeHandler(_run_file_handler)
        try:
            _run_file_handler.close()
        except Exception:
            pass
    _run_file_handler = handler
    root.addHandler(handler)


def get_logger(scope: str) -> logging.Logger:
    return logging.getLogger(f"koan.{scope}")
