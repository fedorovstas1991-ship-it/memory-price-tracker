import logging
import re
import statistics
from datetime import datetime, timezone

import httpx
from selectolax.parser import HTMLParser

from src.config import WATCHLIST, REQUEST_TIMEOUT
from src.currency import convert_usd_to_rub
from src.models import PriceEntry
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

EBAY_SEARCH_URL = (
    "https://www.ebay.com/sch/i.html?_nkw={part_number}&_sacat=0&LH_BIN=1"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html",
    "Accept-Language": "en-US,en;q=0.9",
}


def parse_ebay_search(html: str) -> list[dict]:
    """Parse eBay search results page, return list of {price, title, url} dicts."""
    tree = HTMLParser(html)
    results = []

    for card in tree.css(".s-card--horizontal"):
        # Price
        price_el = card.css_first(".s-card__price")
        if not price_el:
            continue
        price_text = price_el.text(strip=True)
        # Skip range prices like "to" (shown as separate spans for price ranges)
        if not price_text.startswith("$"):
            continue

        # Title — first span inside the header link (avoids "Opens in a new window" span)
        title = ""
        header = card.css_first(".su-card-container__header")
        if header:
            link_el = header.css_first("a")
            if link_el:
                spans = link_el.css("span")
                if spans:
                    title = spans[0].text(strip=True)

        # Skip eBay promotional placeholder cards
        if not title or title.lower() == "shop on ebay":
            continue

        # Link href — use the non-image-treatment anchor
        href = ""
        for link in card.css(".s-card__link"):
            cls = link.attributes.get("class", "")
            if "image-treatment" not in cls:
                href = link.attributes.get("href", "")
                break

        # Parse numeric price (strip $ and commas)
        price_clean = re.sub(r"[^\d.]", "", price_text)
        try:
            price = float(price_clean)
        except ValueError:
            continue

        results.append({"price": price, "title": title, "url": href})

    return results


class EbayScraper(BaseScraper):
    name = "ebay"

    async def fetch_prices(self, rate_usd_rub: float) -> list[PriceEntry]:
        entries: list[PriceEntry] = []
        now = datetime.now(timezone.utc)

        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT, headers=HEADERS, follow_redirects=True
        ) as client:
            for part_number, chip_type, description, capacity in WATCHLIST:
                search_url = EBAY_SEARCH_URL.format(part_number=part_number)
                try:
                    resp = await client.get(search_url)
                    resp.raise_for_status()
                    html = resp.text
                except Exception:
                    logger.warning(
                        "eBay: failed to fetch %s", part_number, exc_info=True
                    )
                    continue

                items = parse_ebay_search(html)
                if not items:
                    logger.info("eBay: no results for %s", part_number)
                    continue

                prices = [item["price"] for item in items]
                median_price = statistics.median(prices)

                # Find item closest to median to use its URL
                closest = min(items, key=lambda x: abs(x["price"] - median_price))

                entries.append(
                    PriceEntry(
                        chip_type=chip_type,
                        part_number=part_number,
                        description=description,
                        capacity=capacity,
                        source="ebay",
                        price_usd=round(median_price, 2),
                        price_rub=convert_usd_to_rub(median_price, rate_usd_rub),
                        moq=1,
                        url=search_url,
                        fetched_at=now,
                    )
                )
                logger.info(
                    "eBay: %s — %d listings, median $%.2f (closest: %s)",
                    part_number,
                    len(prices),
                    median_price,
                    closest["title"][:50],
                )

        return entries
