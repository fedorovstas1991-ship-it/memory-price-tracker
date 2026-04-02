"""eBay crawler stub.

Full Playwright-based implementation will be added separately.
Returns an empty list so the orchestrator can include it without errors.
"""
import logging

logger = logging.getLogger(__name__)


async def crawl(rate_usd_rub: float) -> list[dict]:
    """Stub: eBay crawler not yet implemented."""
    logger.info("eBay: crawler stub — returning empty list")
    return []
