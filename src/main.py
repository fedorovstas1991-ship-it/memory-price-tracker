import asyncio
import logging
import sys

from src.config import LCSC_API_KEY, MOUSER_API_KEY
from src.currency import get_usd_rub_rate
from src.models import PriceEntry
from src.scrapers.lcsc import LCSCScraper
from src.scrapers.mouser import MouserScraper
from src.scrapers.memorymarket import MemoryMarketScraper
from src.scrapers.chipdip import ChipDipScraper
from src.scrapers.findchips import FindChipsScraper
from src.scrapers.szlcsc import SzlcscScraper
from src.sheets import update_prices_sheet, update_history_sheet

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run() -> None:
    logger.info("Starting price fetch...")

    rate = await get_usd_rub_rate()
    logger.info("USD/RUB rate: %.2f", rate)

    scrapers = [
        LCSCScraper(api_key=LCSC_API_KEY),
        MouserScraper(api_key=MOUSER_API_KEY),
        MemoryMarketScraper(),
        ChipDipScraper(),
        FindChipsScraper(),
        SzlcscScraper(),
    ]

    all_entries: list[PriceEntry] = []
    results = await asyncio.gather(
        *[s.fetch_prices(rate) for s in scrapers],
        return_exceptions=True,
    )

    for scraper, result in zip(scrapers, results):
        if isinstance(result, Exception):
            logger.error("Scraper %s failed: %s", scraper.name, result)
        else:
            logger.info("Scraper %s returned %d entries", scraper.name, len(result))
            all_entries.extend(result)

    if not all_entries:
        logger.warning("No entries fetched from any source!")
        return

    logger.info("Total entries: %d. Updating Google Sheets...", len(all_entries))
    update_prices_sheet(all_entries)
    update_history_sheet(all_entries)
    logger.info("Done.")


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
