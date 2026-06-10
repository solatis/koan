# Newest-in-family resolver (brief D6, core-flow F4).
#
# Config-time convenience: given a connection and a family name, queries the
# connection's live model list, identifies all members of the requested family,
# orders them by version using the M2 recognition layer, and returns the newest
# as a pinned model_id with provenance.  The result is a fixed pin -- not a
# floating "latest" pointer -- so the resolved_from field records what was
# pinned and when it was resolved.
#
# Non-listing connection types (bedrock, voyage) and fetch failures propagate
# ModelListingError from list_models_for_connection (the caller requires an
# explicit pin in that case).  A live list that has no members of the requested
# family raises NewestInFamilyUnavailable, a distinct signal so callers can
# surface the two unavailability cases differently (Milestone 6).

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .model_listing import ModelListingError, list_models_for_connection
from .recognition import order_by_version, parse_model_id

if TYPE_CHECKING:
    from ..credentials import CredentialStore
    from ..types import ConfiguredModel, Connection


class NewestInFamilyUnavailable(Exception):
    """Raised when the live list returns no members of the requested family.

    Distinct from ModelListingError (which signals that listing itself failed
    or is unsupported for the connection type).  Callers should suggest an
    explicit model pin or a different family name rather than a retry.
    """


@dataclass(frozen=True)
class NewestResolution:
    """Result of resolve_newest_in_family: a pinned model_id with provenance.

    model_id is the exact versioned id chosen from the live list.
    resolved_from encodes the family, the UTC date of resolution, and the
    pinned id -- kept as a human-readable audit string, never parsed back.
    """

    model_id: str
    resolved_from: str


async def resolve_newest_in_family(
    connection: "Connection",
    family: str,
    store: "CredentialStore | None",
    timeout: float = 8.0,
) -> NewestResolution:
    """Return the newest versioned model in a family from the connection's live list.

    Fetches the live model list via list_models_for_connection (raises
    ModelListingError for non-listing types or fetch failures), filters to
    models whose parsed family matches the requested family, orders by version
    using recognition.order_by_version, and pins the newest.

    Raises:
        ModelListingError: listing is unavailable for this connection type or
            the network/auth call failed.  Caller should require an explicit pin.
        NewestInFamilyUnavailable: the live list returned no members of the
            requested family.  Caller should suggest a different family name
            or an explicit model pin.
    """
    models = await list_models_for_connection(connection, store, timeout)

    # Filter to models whose recognised family matches the requested family.
    # Unrecognised models (parse_model_id returns family=None) are excluded --
    # they cannot be meaningfully version-ordered.
    candidates = [
        m.model for m in models
        if parse_model_id(m.model).family == family
    ]

    if not candidates:
        raise NewestInFamilyUnavailable(
            f"no models in family '{family}' found in the live list "
            f"for connection '{connection.id}' (type '{connection.type}')"
        )

    # order_by_version returns newest-first; take index 0.
    newest = order_by_version(candidates)[0]

    date_str = datetime.now(timezone.utc).date().isoformat()
    resolved_from = f"newest({family})@{date_str} -> {newest}"

    return NewestResolution(model_id=newest, resolved_from=resolved_from)


@dataclass(frozen=True)
class FamilyPin:
    """Per-family newest-version pin computed from a flat model id list.

    family is the canonical family name (from parse_model_id).
    resolved is the exact versioned model id chosen as newest in the family.
    resolved_from encodes the family, the UTC date of resolution, and the
    pinned id -- kept as a human-readable audit string, never parsed back.
    Same format as NewestResolution.resolved_from so display code is uniform.
    """

    family: str
    resolved: str
    resolved_from: str


def resolve_families(model_ids: list[str]) -> list["FamilyPin"]:
    """Return one FamilyPin per recognised family in model_ids, newest-first.

    Groups model_ids by parse_model_id(m).family, skipping models whose family
    is None (unrecognised ids cannot be meaningfully version-ordered).  For each
    family takes order_by_version(members)[0] as the newest.  resolved_from
    follows the same "newest(<family>)@YYYY-MM-DD -> <model_id>" format as
    resolve_newest_in_family so display code is uniform.

    Pure function: no I/O, no network, no state mutation.  Sorting by family
    name produces stable output independent of list ordering.
    """
    from collections import defaultdict

    groups: dict[str, list[str]] = defaultdict(list)
    for m in model_ids:
        fam = parse_model_id(m).family
        if fam is not None:
            groups[fam].append(m)

    date_str = datetime.now(timezone.utc).date().isoformat()
    pins: list[FamilyPin] = []
    for family in sorted(groups):
        newest = order_by_version(groups[family])[0]
        resolved_from = f"newest({family})@{date_str} -> {newest}"
        pins.append(FamilyPin(family=family, resolved=newest, resolved_from=resolved_from))
    return pins


def apply_newest_resolution(
    cm: "ConfiguredModel",
    res: NewestResolution,
) -> "ConfiguredModel":
    """Apply a NewestResolution to a ConfiguredModel in memory.

    Sets cm.model_id and cm.resolved_from to the resolution values.
    In-memory mutation only -- config persistence is Milestone 6.
    Returns cm for call-site convenience.
    """
    cm.model_id = res.model_id
    cm.resolved_from = res.resolved_from
    return cm
