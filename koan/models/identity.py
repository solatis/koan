# Koan's typed model layer — identity, codecs, routes, capabilities, offerings, and pricing.
# Built dark: nothing in the runtime path imports this package yet.

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, NamedTuple, Union


@dataclass(frozen=True)
class ModelIdentity:
    """One model identity regardless of how it is reached.

    The canonical string form `vendor/family-version@snapshot` exists for display
    and config provenance only -- it is never sent on a wire. Identity resolution is
    where "same model, three routes" becomes representable: a ConfiguredModel on
    bedrock and one on anthropic-direct are the same artifact at different prices.
    """

    vendor: str
    family: str
    version: str
    snapshot: str | None = None
    kind: Literal["chat", "embedding"] = "chat"


class Unresolved(NamedTuple):
    """An unresolvable model reference.

    The wire_id passes through verbatim for invocation; everything that consumes it
    knows it is unresolved and says so (the badge / conservative caps path).
    """

    wire_id: str
    route: str


# A model reference that is either a fully resolved identity or an unresolved wire_id.
# Resolved is just ModelIdentity (T1: downstream code never sees raw strings).
ModelRef = Union[ModelIdentity, Unresolved]


def canonical(ident: ModelIdentity) -> str:
    """Return the canonical display/provenance string `vendor/family-version@snapshot`.

    The `@snapshot` segment is omitted when snapshot is None. This form is for display
    and config provenance only -- it is never sent on a wire.
    """
    base = f"{ident.vendor}/{ident.family}-{ident.version}"
    if ident.snapshot is not None:
        return f"{base}@{ident.snapshot}"
    return base


def version_key(ident: ModelIdentity) -> tuple[int, ...]:
    """Extract numeric version segments from `ident.version` for sort ordering.

    Splits on `.` and `-`, keeps only all-digit tokens with <= 5 digits (skipping
    date-stamps like `20250929` which are 8 digits and would incorrectly outrank
    `latest`-style snapshots). Returns a tuple of ints; larger tuples are newer.
    """
    tokens = ident.version.replace(".", "-").split("-")
    nums: list[int] = []
    for t in tokens:
        if t.isdigit() and len(t) <= 5:
            nums.append(int(t))
    return tuple(nums)


def order_by_version(idents: list[ModelIdentity]) -> list[ModelIdentity]:
    """Return identities sorted newest-first by version_key.

    Ordering is based on version_key (the numeric segments of `version` only).
    Ids from different families may be passed together; the relative order among
    different families is arbitrary but stable.
    """
    return sorted(idents, key=version_key, reverse=True)