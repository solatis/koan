# ISO 8601 to milliseconds conversion -- shared between mcp_endpoint and app.py.
# Kept here rather than in web/ so memory-only code paths can import it without
# pulling in the web layer.

from __future__ import annotations

from datetime import datetime, timezone


def iso_to_ms(iso: str) -> int:
    """Convert an ISO 8601 timestamp string to milliseconds since epoch.

    Returns 0 on parse failure rather than raising so callers can use it
    safely in event payloads without try/except boilerplate.
    """
    if not iso:
        return 0
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, OverflowError):
        return 0
