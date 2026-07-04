# Thin model-recognition layer for koan.
#
# Three purposes ONLY (brief D5):
#   1. Version ordering (newest-in-family resolution, Milestone 3)
#   2. Display grouping (family / tier_hint for UI)
#   3. Per-tier defaults (capability resolver falls back to tier_hint)
#
# This is NOT a capability table.  Capability facts (thinking budget limits,
# web-search availability, etc.) live in the PydanticAI model profiles and in
# koan/agents/model_catalog.py.  An unrecognized model id produces recognized=False
# and a warning -- it never raises (brief D5 graceful fallthrough).

from __future__ import annotations

import re
from dataclasses import dataclass

from ..types import ModelTier


# Mapping from canonical family key to (tier_hint, display_group).
_FAMILY_TABLE: dict[str, tuple[ModelTier | None, str]] = {
    # Anthropic
    "claude-opus":        ("strong",   "Claude Opus"),
    "claude-sonnet":      ("standard", "Claude Sonnet"),
    "claude-haiku":       ("cheap",    "Claude Haiku"),
    "claude-fable":       ("strong",   "Claude Fable"),
    # Google
    "gemini-flash-lite":  ("cheap",    "Gemini Flash Lite"),
    "gemini-flash":       ("standard", "Gemini Flash"),
    "gemini-pro":         ("strong",   "Gemini Pro"),
    # OpenAI
    "gpt-4o-mini":        ("standard", "GPT-4o Mini"),
    "gpt-4o":             ("strong",   "GPT-4o"),
    "gpt-4.1-nano":       ("cheap",    "GPT-4.1 Nano"),
    "gpt-4.1-mini":       ("standard", "GPT-4.1 Mini"),
    "gpt-4.1":            ("standard", "GPT-4.1"),
    # Amazon Bedrock native
    "amazon-nova-pro":    ("strong",   "Amazon Nova Pro"),
    "amazon-nova-lite":   ("standard", "Amazon Nova Lite"),
    "amazon-nova-micro":  ("cheap",    "Amazon Nova Micro"),
}

# Override sort keys for model ids whose numeric-segment extraction would produce
# wrong ordering.  The override tuple must beat any realistic extracted value;
# date-stamp tokens (>= 6 digits) are skipped by _parse_version_segments so
# "latest" snapshots get (major, minor, 99999) which sorts after all known dates.
_VERSION_OVERRIDES: dict[str, tuple[int, ...]] = {
    "claude-3-5-sonnet-latest":  (3, 5, 99999),
    "claude-3-5-haiku-latest":   (3, 5, 99999),
    "claude-3-opus-latest":      (3, 0, 99999),
    "gemini-3.1-pro-preview":    (3, 1, 99999),
}

# -- Per-vendor regex patterns for structured parsing -------------------------
#
# Patterns are compiled once at import time.  Each must expose named groups
# `family` and `version` (both optional but present for recognized ids).

# Anthropic new naming:  "claude-{family}-{major}-{minor}[...]"
#   e.g. claude-opus-4-0, claude-sonnet-4-5
_RE_CLAUDE_NEW = re.compile(
    r"^claude-(?P<family>opus|sonnet|haiku|3-haiku|fable)"
    r"-(?P<version>\d+[-\d]*)$",
)

# Anthropic old naming:  "claude-{major}-{minor}-{family}[...]"
#   e.g. claude-3-5-haiku-latest, claude-3-opus-latest
_RE_CLAUDE_OLD = re.compile(
    r"^claude-(?P<version>\d[-\d]*?)-(?P<family>opus|sonnet|haiku)(?:-.*)?$",
)

# Google Gemini:  "gemini-{major}.{minor}-{family}[-{qualifier}...]"
#   e.g. gemini-3.5-flash, gemini-3.1-flash-lite, gemini-3.1-pro-preview
_RE_GEMINI = re.compile(
    r"^gemini-(?P<version>\d+\.\d+)"
    r"-(?P<family>flash-lite|flash|pro)(?:-.*)?$",
)

# OpenAI GPT:  "gpt-{family-token}[-{snapshot}...]"
#   Family tokens are matched in longest-first order to handle overlapping prefixes.
_RE_GPT = re.compile(
    r"^(?P<family>gpt-4o-mini|gpt-4o|gpt-4\.1-nano|gpt-4\.1-mini|gpt-4\.1)"
    r"(?P<version>-.*)?$",
)

# OpenAI o-series:  "o{N}[-{variant}...]"  -- no koan family entry, unrecognized.
_RE_O_SERIES = re.compile(r"^o\d+")

# Amazon Bedrock native:  "amazon.{family}-v{version}:{qualifier}"
_RE_AMAZON = re.compile(
    r"^amazon[.-](?P<family>nova-pro|nova-lite|nova-micro)"
    r"-v(?P<version>\d+)(?::\d+)?$",
)


@dataclass(frozen=True)
class ParsedModel:
    """Output of parse_model_id: structured family/tier/version parse.

    recognized=False means the model id was not found in the family table and
    the other fields are best-effort inferences (or None).  The caller must not
    raise on unrecognized ids; they degrade to conservative defaults (brief D5).
    """

    family: str | None
    tier_hint: ModelTier | None
    version: str | None
    recognized: bool


def _lookup_family(family_key: str) -> tuple[ModelTier | None, str]:
    """Look up a family key in _FAMILY_TABLE; return (None, '') if absent."""
    return _FAMILY_TABLE.get(family_key, (None, ""))


def _make_parsed(family_key: str, version: str | None) -> ParsedModel:
    """Build a ParsedModel for a known family_key."""
    tier, _ = _lookup_family(family_key)
    return ParsedModel(
        family=family_key,
        tier_hint=tier,
        version=version or None,
        recognized=family_key in _FAMILY_TABLE,
    )


def parse_model_id(model_id: str) -> ParsedModel:
    """Parse a model id into its family, tier_hint, and version.

    Handles three main naming conventions:
      - Anthropic new: "claude-{family}-{version}"
      - Anthropic old: "claude-{version}-{family}"
      - Gemini:        "gemini-{version}-{family}[-{qualifier}]"
      - OpenAI GPT:    "gpt-{family-token}[-{snapshot}]"
      - Amazon Bedrock:"amazon.{nova-family}-v{version}[:{qualifier}]"

    The Bedrock vendor prefix "anthropic." is stripped before matching so that
    Bedrock-hosted Anthropic model ids resolve correctly.

    Returns recognized=False for ids not matching any pattern -- never raises.
    """
    if not model_id:
        return ParsedModel(family=None, tier_hint=None, version=None, recognized=False)

    norm = model_id.lower()

    # Strip Bedrock vendor prefix so "anthropic.claude-opus-4-0" -> "claude-opus-4-0".
    if norm.startswith("anthropic."):
        norm = norm[len("anthropic."):]

    try:
        # Anthropic new naming first (more specific).
        m = _RE_CLAUDE_NEW.match(norm)
        if m:
            fam = m.group("family")
            # "3-haiku" is a legacy variant; map to "claude-haiku" family.
            family_key = "claude-haiku" if fam == "3-haiku" else f"claude-{fam}"
            return _make_parsed(family_key, m.group("version"))

        # Anthropic old naming.
        m = _RE_CLAUDE_OLD.match(norm)
        if m:
            family_key = f"claude-{m.group('family')}"
            return _make_parsed(family_key, m.group("version"))

        # Google Gemini.
        m = _RE_GEMINI.match(norm)
        if m:
            family_key = f"gemini-{m.group('family')}"
            return _make_parsed(family_key, m.group("version"))

        # OpenAI GPT families (longest match via alternation in regex).
        m = _RE_GPT.match(norm)
        if m:
            family_key = m.group("family")
            version_str = m.group("version")
            return _make_parsed(family_key, version_str.lstrip("-") if version_str else None)

        # Amazon Bedrock native models.
        m = _RE_AMAZON.match(norm)
        if m:
            family_key = f"amazon-{m.group('family')}"
            return _make_parsed(family_key, m.group("version"))

    except Exception:
        pass

    # Unrecognized -- return best-effort None fields without raising.
    return ParsedModel(family=None, tier_hint=None, version=None, recognized=False)


def _parse_version_segments(model_id: str) -> tuple[int, ...]:
    """Extract numeric version segments from a model id for sort ordering.

    Splits on "." and "-", keeps only all-digit tokens that look like version
    numbers (5 or fewer digits -- skipping date-stamps like "20241022" which are
    8 digits and would incorrectly outrank "latest"-style snapshots).
    """
    tokens = model_id.replace(".", "-").split("-")
    nums: list[int] = []
    for t in tokens:
        if t.isdigit() and len(t) <= 5:
            nums.append(int(t))
    return tuple(nums)


def version_key(model_id: str) -> tuple[int, ...]:
    """Return a comparable sort key for version ordering within a family.

    Honors _VERSION_OVERRIDES for ids with non-lexical ordering (e.g. "latest"
    snapshots).  For all other ids, extracts numeric segments (skipping date
    stamps) from the id.  Larger tuples are newer.
    """
    if model_id in _VERSION_OVERRIDES:
        return _VERSION_OVERRIDES[model_id]
    return _parse_version_segments(model_id)


def order_by_version(model_ids: list[str]) -> list[str]:
    """Return model ids sorted newest-first within a family.

    Ordering is based on version_key.  Ids from different families may be
    passed together; the relative order among different families is arbitrary
    but stable.  Used by the newest-in-family resolver (Milestone 3).
    """
    return sorted(model_ids, key=version_key, reverse=True)
