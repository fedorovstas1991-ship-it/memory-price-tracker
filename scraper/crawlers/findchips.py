"""FindChips full-catalog crawler.

Searches by category keyword and paginates through ALL results pages.
Uses the page=N query parameter supported by FindChips search.
"""
import asyncio
import json
import logging
from html import unescape

import httpx
from selectolax.parser import HTMLParser

from scraper.brand import extract_brand

logger = logging.getLogger(__name__)

CATEGORIES = [
    "eMMC",
    "UFS",
    "DDR4 SDRAM",
    "DDR5 SDRAM",
    "LPDDR4",
    "LPDDR5",
    "NAND Flash",
    "NOR Flash",
    "SRAM",
    "DDR3 SDRAM",
]

SEARCH_URL = "https://www.findchips.com/search/{keyword}"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

MAX_PAGES = 20
PAGE_DELAY = 1.5  # seconds between requests


def _parse_page(html: str) -> list[dict]:
    """Parse distributor rows from one FindChips search result page."""
    tree = HTMLParser(html)
    results = []
    seen: set[str] = set()

    for tr in tree.css("tr[data-distributor_name][data-price]"):
        distributor = tr.attributes.get("data-distributor_name", "")
        mfr_part = tr.attributes.get("data-mfrpartnumber", "") or ""
        stock_str = tr.attributes.get("data-instock", "0") or "0"
        price_raw = tr.attributes.get("data-price", "[]") or "[]"
        desc_el = tr.css_first("td.description, td[data-description]")
        description = desc_el.text(strip=True) if desc_el else ""

        if not distributor:
            continue

        key = f"{distributor}:{mfr_part}"
        if key in seen:
            continue
        seen.add(key)

        try:
            price_data = json.loads(unescape(price_raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

        # Pick best USD price: prefer low-qty tier
        best_price = None
        best_moq = 1
        for tier in price_data:
            if len(tier) >= 3 and tier[1] == "USD":
                try:
                    qty = int(tier[0])
                    price = float(tier[2])
                except (ValueError, TypeError):
                    continue
                if qty <= 10:
                    best_price = price
                    best_moq = qty
                elif best_price is None:
                    best_price = price
                    best_moq = qty

        if best_price is None or best_price <= 0:
            continue

        try:
            stock = int(stock_str.replace(",", ""))
        except ValueError:
            stock = 0

        results.append({
            "part_number": mfr_part,
            "description": description,
            "brand": extract_brand(mfr_part, description),
            "source": "findchips",
            "distributor": distributor,
            "price_usd": round(best_price, 2),
            "price_rub": None,
            "price_cny": None,
            "moq": best_moq,
            "stock": stock,
        })

    return results


def _has_more_results(html: str) -> bool:
    """Return True if there is a next-page link or more items to load."""
    tree = HTMLParser(html)
    # FindChips uses a "Load more" button or pagination links
    if tree.css_first("a.pagination-next, a[rel='next'], .load-more"):
        return True
    return False


async def crawl(rate_usd_rub: float) -> list[dict]:
    """Crawl FindChips across all CATEGORIES with pagination."""
    all_entries: list[dict] = []

    async with httpx.AsyncClient(
        timeout=20,
        headers=BROWSER_HEADERS,
        follow_redirects=True,
    ) as client:
        for category in CATEGORIES:
            category_count = 0
            keyword = category.replace(" ", "+")
            base_url = SEARCH_URL.format(keyword=keyword)

            for page in range(1, MAX_PAGES + 1):
                url = f"{base_url}?page={page}" if page > 1 else base_url
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    items = _parse_page(resp.text)
                    if not items:
                        logger.info(
                            "FindChips: category=%r page %d — no items, stopping",
                            category, page,
                        )
                        break

                    # Attach category-derived chip_type and url
                    for item in items:
                        item["chip_type"] = category
                        item["capacity"] = ""
                        item["url"] = (
                            f"https://www.findchips.com/search/"
                            f"{item['part_number']}"
                            if item["part_number"]
                            else base_url
                        )

                    all_entries.extend(items)
                    category_count += len(items)

                    logger.info(
                        "FindChips: category=%r page %d, %d items on page, %d total",
                        category, page, len(items), category_count,
                    )

                    if not _has_more_results(resp.text):
                        break

                    await asyncio.sleep(PAGE_DELAY)

                except Exception:
                    logger.warning(
                        "FindChips: category=%r page %d — error, skipping",
                        category, page, exc_info=True,
                    )
                    break

            logger.info(
                "FindChips: category=%r done, %d items", category, category_count,
            )

    logger.info("FindChips: crawl complete, %d total entries", len(all_entries))
    return all_entries
