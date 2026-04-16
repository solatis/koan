from json_repair import repair_json


def parse_partial(buffer: str) -> dict | None:
    """Lenient parser for truncated JSON from streaming input_json_delta fragments."""
    if not buffer.strip():
        return None
    try:
        repaired = repair_json(buffer, return_objects=True)
        return repaired if isinstance(repaired, dict) else None
    except (ValueError, TypeError):
        return None
