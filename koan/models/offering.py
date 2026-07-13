# Offering: the join of a model identity and a hosting route -- the only thing
# runtime code sees (design §2.5).

from __future__ import annotations

from dataclasses import dataclass

from .capabilities import (
    Capabilities,
    base_catalog_lookup,
    get_pydantic_ai_profile,
    merge_capabilities,
    profile_to_caps,
    route_overlay_for,
)
from .codecs import CODECS, render_bare_id
from .identity import ModelIdentity, ModelRef, Unresolved
from .pricing import PriceRef, price_for
from .routes import Route, get_route


@dataclass(frozen=True)
class Offering:
    """The join of a model identity and a hosting route -- the only thing runtime code sees.

    `wire_id` is exactly what goes on the wire (verbatim if the user typed an unknown id;
    the codec-parsed form for catalog entries). `ref` is the resolved identity or an
    Unresolved passthrough. `caps` is the merged, provenance-carrying capability record.
    `price` is the per-offering rate card (None when the route has no price source).
    `locality` is the geo/region extracted from the wire_id (e.g. "eu" for bedrock-converse),
    stored for downstream picker rendering and endpoint construction.
    """

    route: Route
    wire_id: str
    ref: ModelRef
    caps: Capabilities
    price: PriceRef | None
    locality: str | None = None


def resolve_offering(route_id: str, model_string: str) -> Offering:
    """The single constructor for an Offering.

    Called once at config time (display/validation) and once at run-freeze time (into the
    flatten pipeline). It is the ONLY place `NamingCodec.parse` runs; after this point no
    string parsing happens anywhere (T1). Flow:

      1. Look up the Route via get_route(route_id).
      2. Look up the NamingCodec via CODECS[route.naming].
      3. Parse model_string -> (ModelRef, locality).
      4. Resolved + in catalog: base intrinsics -> route overlay -> profile facts, merge.
         Resolved + not in catalog: conservative defaults (inferred) -> overlay -> profile.
      5. Unresolved: conservative defaults (unknown), resolved=False, no overlay/profile.
      6. Look up price via price_for.
      7. Return Offering(route, model_string, ref, caps, price, locality).
    """
    route = get_route(route_id)
    codec = CODECS[route.naming]
    ref, locality = codec.parse(model_string)

    if isinstance(ref, ModelIdentity):
        base = base_catalog_lookup(ref.vendor, ref.family, ref.version)
        resolved = True
        if base is None:
            # Resolved identity but not in the curated catalog: conservative intrinsics with
            # `inferred` provenance. The route overlay + profile still apply (the identity is
            # resolved, so route-scoped truth and substrate facts are valid for it).
            from .capabilities import _conservative_caps  # local import: avoids exposing the private name at module top
            base = _conservative_caps(resolved=True, prov_source="inferred")
        overlay = route_overlay_for(route.capability_overlay)
        # Profile facts only for chat models; embeddings have no pydantic-ai profile.
        profile_caps = None
        if ref.kind == "chat":
            bare_id = render_bare_id(ref) or model_string
            profile = get_pydantic_ai_profile(route.dialect, ref.vendor, bare_id)
            if profile:
                profile_caps = profile_to_caps(profile)
        caps = merge_capabilities(base, overlay, profile_caps, resolved)
    else:
        # Unresolved: conservative defaults, all-unknown provenance, resolved=False.
        from .capabilities import _conservative_caps
        base = _conservative_caps(resolved=False, prov_source="unknown")
        caps = merge_capabilities(base, None, None, resolved=False)

    offering = Offering(route=route, wire_id=model_string, ref=ref, caps=caps, price=None, locality=locality)
    # Price lookup is a separate step so an unstable snapshot never invalidates the
    # already-built caps/ref. price_for degrades to "unavailable" on any failure.
    price = price_for(offering)
    return Offering(route=route, wire_id=model_string, ref=ref, caps=caps, price=price, locality=locality)