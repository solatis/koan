"""Koan's typed model layer -- identity, codecs, routes, capabilities, offerings, and pricing.

Live: the runtime path (adapter, registry, guard, config, types, memory) imports this
package. The package uses only stdlib plus defensive pydantic-ai profile reads and
genai-prices; no runtime path depends on it.
"""

from __future__ import annotations

from .capabilities import (
    Capabilities,
    CacheSupport,
    Provenance,
    StructuredSupport,
    ThinkingSupport,
    embedding_capabilities,
    merge_capabilities,
)
from .codecs import (
    CODECS,
    NamingCodec,
    split_bedrock_model_id,
)
from .identity import (
    ModelIdentity,
    ModelRef,
    Unresolved,
    canonical,
    order_by_version,
    version_key,
)
from .offering import (
    Offering,
    resolve_offering,
)
from .pricing import (
    PriceRef,
    price_for,
    price_for_usage,
)
from .routes import (
    AuthScheme,
    ListingStrategy,
    ROUTES,
    Route,
    get_route,
    route_ids,
)

__all__ = [
    "ModelIdentity",
    "Unresolved",
    "ModelRef",
    "canonical",
    "version_key",
    "order_by_version",
    "NamingCodec",
    "CODECS",
    "split_bedrock_model_id",
    "AuthScheme",
    "ListingStrategy",
    "Route",
    "ROUTES",
    "get_route",
    "route_ids",
    "Provenance",
    "ThinkingSupport",
    "CacheSupport",
    "StructuredSupport",
    "Capabilities",
    "merge_capabilities",
    "embedding_capabilities",
    "Offering",
    "PriceRef",
    "resolve_offering",
    "price_for",
    "price_for_usage",
]