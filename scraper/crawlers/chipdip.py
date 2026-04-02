"""ChipDip full-catalog crawler.

Crawls https://www.chipdip.ru/catalog-show/ic-memory through ALL pages by
incrementing x.page until no items are returned.
"""
import asyncio
import logging
import re

import httpx
from selectolax.parser import HTMLParser

from scraper.brand import extract_brand

logger = logging.getLogger(__name__)

CATALOG_URL = "https://www.chipdip.ru/catalog-show/ic-memory"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

MAX_PAGES = 100
PAGE_DELAY = 1.5


def _parse_rub_price(text: str) -> float:
    cleaned = re.sub(r"[^\d,.]", "", text).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_catalog_page(html: str) -> list[dict]:
    """Extract product items from one ChipDip catalog HTML page."""
    tree = HTMLParser(html)
    items = []
    seen_urls: set[str] = set()

    for item in tree.css(".catalog-item, .product-item, [class*='item']"):
        link = item.css_first("a.link, a[href*='/product/']")
        price_el = item.css_first(".price, [class*='price']")
        desc_el = item.css_first(".description, [class*='desc']")
        if not link or not price_el:
            continue
        part_number = link.text(strip=True)
        href = link.attributes.get("href", "")
        price_text = price_el.text(strip=True)
        price_rub = _parse_rub_price(price_text)
        if price_rub <= 0:
            continue
        url = f"https://www.chipdip.ru{href}" if href.startswith("/") else href
        if url in seen_urls:
            continue
        seen_urls.add(url)
        description = desc_el.text(strip=True) if desc_el else ""
        items.append({
            "part_number": part_number,
            "description": description,
            "price_rub": price_rub,
            "url": url,
        })

    return items


def _has_next_page(html: str) -> bool:
    """Return True if there is a pagination next-page link."""
    tree = HTMLParser(html)
    return bool(
        tree.css_first(
            "a.pagination__next, a[rel='next'], .pagination .next, "
            "a[class*='next'][href], li.next a"
        )
    )


async def crawl(rate_usd_rub: float) -> list[dict]:
    """Crawl all ChipDip ic-memory catalog pages."""
    all_entries: list[dict] = []

    async with httpx.AsyncClient(
        timeout=20,
        headers=BROWSER_HEADERS,
        follow_redirects=True,
    ) as client:
        for page in range(1, MAX_PAGES + 1):
            params = {"x.page": page}
            try:
                resp = await client.get(CATALOG_URL, params=params)
                resp.raise_for_status()
                items = _parse_catalog_page(resp.text)

                if not items:
                    logger.info(
                        "ChipDip: page %d — no items, stopping", page,
                    )
                    break

                for item in items:
                    price_usd = (
                        round(item["price_rub"] / rate_usd_rub, 2)
                        if rate_usd_rub
                        else None
                    )
                    price_rub = item["price_rub"]
                    part_number = item["part_number"]
                    description = item["description"]
                    all_entries.append({
                        "chip_type": "Memory IC",
                        "part_number": part_number,
                        "description": description,
                        "brand": extract_brand(part_number, description),
                        "capacity": "",
                        "source": "chipdip",
                        "distributor": "ChipDip",
                        "price_usd": price_usd,
                        "price_rub": price_rub,
                        "price_cny": None,
                        "moq": 1,
                        "stock": 0,
                        "url": item["url"],
                    })

                logger.info(
                    "ChipDip: page %d, %d items on page, %d total",
                    page, len(items), len(all_entries),
                )

                if not _has_next_page(resp.text):
                    logger.info("ChipDip: no next page after page %d, stopping", page)
                    break

                await asyncio.sleep(PAGE_DELAY)

            except Exception:
                logger.warning(
                    "ChipDip: page %d — error, skipping", page, exc_info=True,
                )
                break

    logger.info("ChipDip: crawl complete, %d total entries", len(all_entries))
    return all_entries
