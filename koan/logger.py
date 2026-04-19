# Logging setup for the koan server.
# Call setup_logging() once at startup; use get_logger(scope) everywhere else.

import logging
from pathlib import Path

_FORMAT = "%(asctime)s [%(name)s] %(levelname)s %(message)s"
_configured = False


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
    root = logging.getLogger("koan")
    log_path = Path(run_dir) / "koan.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(str(log_path))
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)


def get_logger(scope: str) -> logging.Logger:
    return logging.getLogger(f"koan.{scope}")
