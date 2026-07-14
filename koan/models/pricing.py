# Pricing: per-offering price rate card via the genai-prices bundled snapshot.

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
# Real import so the `Offering` annotation resolves under --debug runtime type
# enforcement (beartype). The old circular import is broken on the other side:
# offering.py defers its price_for import into resolve_offering.
from .offering import Offering


@dataclass(frozen=True)
class PriceRef:
    """Per-million rate card for one offering, joined from the genai-prices snapshot.

    `input_per_million`/`output_per_million` are the per-million-token rates (independent
    of any request's token counts); `source` names where the rate came from. Routes
    price differently (regional premiums, openrouter markup), so the price is per-offering
    rather than per-identity. `None` rates with source "unavailable" mean the route has no
    price source or the snapshot lookup failed -- cost stays 0, no functional regression.
    """

    input_per_million: Decimal | None
    output_per_million: Decimal | None
    source: str


def price_for(
    offering: Offering,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> PriceRef:
    """Return the per-million rate card for an offering from the genai-prices snapshot.

    Thin wrapper over `genai_prices.calc_price`. Uses `offering.route.price_source` as the
    genai-prices provider id and `offering.wire_id` as the model reference. The returned
    `PriceRef` holds per-million RATES (token-independent); the token parameters are
    accepted for API symmetry and future cost computation but do not alter the rate card.

    Returns `PriceRef(None, None, "unavailable")` when `price_source` is None or the
    snapshot lookup fails (Assumption 4: cost stays 0, no functional regression).
    """
    price_source = offering.route.price_source
    if price_source is None:
        return PriceRef(input_per_million=None, output_per_million=None, source="unavailable")
    try:
        import genai_prices

        # Per-million rates are model-level: compute by pricing exactly one million tokens
        # of each axis. We make two cheap snapshot lookups (input-only, then output-only)
        # so the rate card separates input and output rates regardless of a request's mix.
        input_ref = genai_prices.calc_price(
            genai_prices.Usage(input_tokens=1_000_000, output_tokens=0),
            model_ref=offering.wire_id,
            provider_id=price_source,
        )
        output_ref = genai_prices.calc_price(
            genai_prices.Usage(input_tokens=0, output_tokens=1_000_000),
            model_ref=offering.wire_id,
            provider_id=price_source,
        )
        return PriceRef(
            input_per_million=Decimal(str(input_ref.input_price)),
            output_per_million=Decimal(str(output_ref.output_price)),
            source=price_source,
        )
    except Exception:
        # Defensive: an unresolvable model or a snapshot gap degrades to "unavailable"
        # rather than raising (Assumption 4 / brief D5 graceful fallthrough).
        return PriceRef(input_per_million=None, output_per_million=None, source="unavailable")

def price_for_usage(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Decimal:
    """Bridge: compute cost from (provider, model, tokens) using genai-prices.

    M2 bridge -- matches the old ``model_catalog.price_for_usage`` signature so
    ``projections.py`` continues to work until M3 replaces this with offering-based
    cost derivation. Maps the route id to a genai-prices provider id via the route
    registry's ``price_source`` field, then calls ``genai_prices.calc_price``.

    Returns the total price as a Decimal (never negative; raises on unresolvable
    model). Providers without a ``price_source`` (e.g. ollama-cloud, voyage) raise
    ValueError, which the projection fold catches -- cost stays 0 for those routes.
    """
    import genai_prices
    from .routes import ROUTES

    # Map route id -> genai-prices provider id via the route registry.
    route_price_source = {r.id: r.price_source for r in ROUTES}
    genai_provider = route_price_source.get(provider)
    if genai_provider is None:
        raise ValueError(f"no genai-prices mapping for provider {provider!r}")

    usage = genai_prices.Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens if cache_read_tokens else None,
        cache_write_tokens=cache_write_tokens if cache_write_tokens else None,
    )
    result = genai_prices.calc_price(usage, model_ref=model, provider_id=genai_provider)
    return Decimal(str(result.total_price))