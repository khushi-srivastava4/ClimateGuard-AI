"""Shared bounded HTTP timeouts for external data providers."""

import httpx

from app.config import settings


def provider_timeout() -> httpx.Timeout:
    """Fast providers (weather forecast): everything capped at a few seconds."""
    budget = max(settings.HTTP_TIMEOUT, 0.1)
    return httpx.Timeout(
        connect=min(budget, 4.0),
        read=min(budget, 8.0),
        write=min(budget, 5.0),
        pool=min(budget, 2.0),
    )


def slow_provider_timeout() -> httpx.Timeout:
    """Slow public portals (data.gov.in Agmarknet, ISRIC SoilGrids) routinely need 10-25 s to answer.

    The 8 s read cap of provider_timeout() made them raise ReadTimeout on every request. The graph still enforces
    an overall per-provider budget, so a slow portal cannot hold up the whole advisory.
    """
    budget = max(settings.HTTP_TIMEOUT, 0.1)
    return httpx.Timeout(
        connect=min(budget, 8.0),
        read=min(max(budget, 25.0), 28.0),
        write=min(budget, 5.0),
        pool=min(budget, 3.0),
    )
