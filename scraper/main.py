"""Memory price tracker — full catalog crawl orchestrator.

Runs all crawlers concurrently, merges results, and writes to PostgreSQL.
"""
import asyncio
import logging
import sys

from scraper.currency import get_usd_rub_rate
from scraper.db import get_pool, write_prices, append_history
from scraper.crawlers import findchips, szlcsc, jlcpcb, memorymarket, chipdip, ebay

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def run() -> None:
    logger.info("=== Memory Price Tracker starting ===")

    # Step 1: get exchange rate
    rate = await get_usd_rub_rate()
    logger.info("USD/RUB rate: %.2f", rate)

    # Step 2: run all crawlers concurrently
    logger.info("Launching all crawlers...")
    crawler_fns = [
        ("findchips", findchips.crawl),
        ("szlcsc", szlcsc.crawl),
        ("jlcpcb", jlcpcb.crawl),
        ("memorymarket", memorymarket.crawl),
        ("chipdip", chipdip.crawl),
        ("ebay", ebay.crawl),
    ]

    results = await asyncio.gather(
        *[fn(rate) for _, fn in crawler_fns],
        return_exceptions=True,
    )

    # Step 3: merge results
    all_entries: list[dict] = []
    for (name, _), result in zip(crawler_fns, results):
        if isinstance(result, Exception):
            logger.error("Crawler %s raised an exception: %s", name, result, exc_info=result)
        else:
            logger.info("Crawler %s returned %d entries", name, len(result))
            all_entries.extend(result)

    if not all_entries:
        logger.warning("No entries collected from any crawler — nothing to write.")
        return

    logger.info("Total entries collected: %d", len(all_entries))

    # Step 4: write to PostgreSQL
    pool = await get_pool()
    try:
        await write_prices(pool, all_entries)
        await append_history(pool, all_entries)
    finally:
        await pool.close()

    # Step 5: summary
    sources: dict[str, int] = {}
    for entry in all_entries:
        src = entry.get("source") or "unknown"
        sources[src] = sources.get(src, 0) + 1

    logger.info("=== Crawl summary ===")
    for src, count in sorted(sources.items(), key=lambda x: -x[1]):
        logger.info("  %-20s %d entries", src, count)
    logger.info("=== Done. Total: %d entries ===", len(all_entries))


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
