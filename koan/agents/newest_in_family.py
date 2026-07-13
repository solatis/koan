# Family-pin resolver over the curated catalog (brief D6, core-flow F4).
#
# M2: the async resolve_newest_in_family (live-list I/O), NewestResolution,
# NewestInFamilyUnavailable, apply_newest_resolution, and the bridge helpers
# _parse_family / _order_model_ids_by_version are deleted. The
# /api/config/models/newest endpoint is deleted too -- family grouping data
# now lives in offerings_by_connection identity fields (the frontend derives
# pins from there).
#
# What survives is FamilyPin and resolve_families: a pure function over
# _BASE_CATALOG in koan.models.capabilities. It is a utility/test surface --
# no runtime caller after the provider_models event deletion (Finding M1).

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class FamilyPin:
    """Per-family newest-version pin computed from the curated catalog.

    family is the canonical family name (e.g. "claude-sonnet").
    resolved is the canonical display string for the newest member of the family
    (vendor/family-version), so display code is uniform with offerings.
    resolved_from encodes the family, the UTC date of resolution, and the
    pinned id -- kept as a human-readable audit string, never parsed back.
    """

    family: str
    resolved: str
    resolved_from: str


def resolve_families(catalog=None) -> list["FamilyPin"]:
    """Return one FamilyPin per family in the curated catalog, newest-first.

    Pure function over _BASE_CATALOG in koan.models.capabilities. Groups catalog
    entries by family, picks the newest by version_key, and returns FamilyPin
    objects. No network, no model-listing I/O. The resolved_from date stamp
    uses datetime.now(timezone.utc) so the function is deterministic except for
    that date component. Utility/test surface -- family grouping data is
    embedded in offerings_by_connection identity fields for frontend consumption.
    """
    from collections import defaultdict
    from koan.models.capabilities import _BASE_CATALOG
    from koan.models.identity import ModelIdentity, version_key, canonical

    catalog = catalog or _BASE_CATALOG
    groups: dict[str, list[ModelIdentity]] = defaultdict(list)
    for (vendor, family, version), caps in catalog.items():
        kind = "embedding" if caps.embedding_dims else "chat"
        ident = ModelIdentity(vendor=vendor, family=family, version=version, kind=kind)
        groups[family].append(ident)

    date_str = datetime.now(timezone.utc).date().isoformat()
    pins: list[FamilyPin] = []
    for family in sorted(groups):
        newest = sorted(groups[family], key=version_key, reverse=True)[0]
        resolved = canonical(newest)
        resolved_from = f"newest({family})@{date_str} -> {resolved}"
        pins.append(FamilyPin(family=family, resolved=resolved, resolved_from=resolved_from))
    return pins