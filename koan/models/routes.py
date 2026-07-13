# Route registry: the hosting axis as data. Adding a route is a registry entry.

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


AuthScheme = Literal["api_key", "bearer", "aws_sigv4", "none"]
"""How a route authenticates: static api_key, bearer token, AWS sigv4, or none."""

ListingStrategy = Literal["native", "openai_compat"]
"""How a route lists models: a native provider API, or an OpenAI-compat /v1/models endpoint."""


@dataclass(frozen=True)
class Route:
    """One hosting route.

    Data, not code -- adding a route is a registry entry (operator, dialect, auth,
    endpoint template, naming codec, localities, listing strategy, capability overlay,
    price source). Only a genuinely new wire protocol justifies new dialect code (T3).
    """

    id: str
    operator: str
    dialect: str
    auth: AuthScheme
    endpoint_template: str | None
    naming: str                       # key into CODECS (codecs.py)
    localities: tuple[str, ...]
    listing: ListingStrategy | None
    capability_overlay: str | None    # key into _ROUTE_OVERLAYS (capabilities.py)
    price_source: str | None          # genai-prices provider id


# The registry. Append-only data; the route count grows constantly (T3), so routes
# must be data. The current _PROVIDER_PREFIX, _KEY_REQUIRING_PROVIDERS, listing
# dispatch, PROVIDER_ID_MAP, and both cache-transport sets collapse into these fields.
# Localities: 'global' for single-region routes; the bedrock geo set for bedrock-converse.
ROUTES: tuple[Route, ...] = (
    Route(
        id="anthropic", operator="anthropic", dialect="anthropic-messages",
        auth="api_key", endpoint_template=None, naming="anthropic",
        localities=("global",), listing="native",
        capability_overlay="anthropic", price_source="anthropic",
    ),
    Route(
        id="openai", operator="openai", dialect="openai-chat",
        auth="api_key", endpoint_template=None, naming="openai",
        localities=("global",), listing="native",
        capability_overlay="openai", price_source="openai",
    ),
    Route(
        id="google", operator="google", dialect="google-genai",
        auth="api_key", endpoint_template=None, naming="google",
        localities=("global",), listing="native",
        capability_overlay="google", price_source="google",
    ),
    Route(
        id="bedrock-converse", operator="aws", dialect="bedrock-converse",
        auth="api_key", endpoint_template=None, naming="bedrock-converse",
        localities=("us", "eu", "apac", "jp", "au", "ca", "global", "us-gov"),
        listing=None,
        capability_overlay="bedrock-converse", price_source="aws",
    ),
    # bedrock-mantle: Anthropic API via the AWS Bedrock Mantle endpoint. Same
    # dialect as anthropic-direct (anthropic-messages); the {region} in the
    # endpoint_template is substituted by the connection's locality at build
    # time (generic adapter plumbing, not dialect code -- Decision 4).
    Route(
        id="bedrock-mantle", operator="aws", dialect="anthropic-messages",
        auth="bearer", endpoint_template="https://bedrock-mantle.{region}.api.aws/anthropic",
        naming="bedrock-mantle",
        localities=("us", "eu", "apac", "jp", "au", "ca", "global", "us-gov"),
        listing=None,
        capability_overlay="bedrock-mantle", price_source="aws",
    ),
    Route(
        id="openrouter", operator="openrouter", dialect="openai-chat",
        auth="api_key", endpoint_template=None, naming="openrouter",
        localities=("global",), listing="openai_compat",
        capability_overlay="openrouter", price_source="openrouter",
    ),
    Route(
        id="ollama-cloud", operator="ollama", dialect="openai-chat",
        auth="api_key", endpoint_template="https://ollama.com/v1", naming="ollama-cloud",
        localities=("global",), listing="openai_compat",
        capability_overlay="ollama-cloud", price_source=None,
    ),
    Route(
        id="voyage", operator="voyage", dialect="voyage-embeddings",
        auth="api_key", endpoint_template=None, naming="voyage",
        localities=("global",), listing=None,
        capability_overlay="voyage", price_source=None,
    ),
)


def get_route(route_id: str) -> Route:
    """Look up a route by id. Raises KeyError for unknown ids -- the registry is the
    sole validation source (T3), so an unknown route id is a config error, not a
    graceful fallthrough."""
    for route in ROUTES:
        if route.id == route_id:
            return route
    raise KeyError(route_id)


def route_ids() -> tuple[str, ...]:
    """Return all route ids in registry order."""
    return tuple(r.id for r in ROUTES)