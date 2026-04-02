"""MemoryMarket full-catalog crawler.

Scrapes the main spot index pages at memorymarket.com and attempts to follow
category and pagination links to collect all available spot prices.
Also probes individual price detail pages at /price/in/ID.
"""
import asyncio
import logging
import re

import httpx
from selectolax.parser import HTMLParser

from scraper.brand import extract_brand

logger = logging.getLogger(__name__)

BASE_URL = "https://www.memorymarket.com"
INDEX_URL = f"{BASE_URL}/"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

PAGE_DELAY = 2.0
MAX_DETAIL_PAGES = 200  # max individual /price/in/ID pages to probe


def _parse_rub_price(text: str) -> float:
    cleaned = re.sub(r"[^\d.]", "", text)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_spot_tables(html: str, page_url: str) -> list[dict]:
    """Extract all spot price rows from HTML tables on a page."""
    tree = HTMLParser(html)
    results = []
    for table in tree.css("table"):
        headers = [th.text(strip=True).lower() for th in table.css("thead th, th")]
        for tr in table.css("tbody tr, tr"):
            cells = [td.text(strip=True) for td in tr.css("td")]
            if len(cells) < 3:
                continue
            product = cells[0]
            spec = cells[1] if len(cells) > 1 else ""
            price_str = cells[2].replace(",", "").replace("$", "").strip()
            try:
                price_usd = float(price_str) if price_str else 0.0
            except ValueError:
                price_usd = 0.0
            if price_usd <= 0:
                continue
            results.append({
                "chip_type": product,
                "part_number": f"{product} {spec}".strip(),
                "description": f"{product} {spec} spot".strip(),
                "brand": extract_brand(product, f"{product} {spec}"),
                "capacity": spec,
                "source": "memorymarket",
                "distributor": "MemoryMarket",
                "price_usd": round(price_usd, 2),
                "price_rub": None,
                "price_cny": None,
                "moq": 0,
                "stock": 0,
                "url": page_url,
            })
    return results


def _collect_category_links(html: str) -> list[str]:
    """Find links to category or pagination sub-pages."""
    tree = HTMLParser(html)
    links = set()
    for a in tree.css("a[href]"):
        href = a.attributes.get("href", "")
        if not href:
            continue
        # Relative → absolute
        if href.startswith("/"):
            href = BASE_URL + href
        elif not href.startswith("http"):
            continue
        # Only same-domain links that look like category or price pages
        if BASE_URL not in href:
            continue
        if any(seg in href for seg in ["/price/", "/spot/", "/market/", "/category/", "/index/"]):
            links.add(href)
    return list(links)


async def crawl(rate_usd_rub: float) -> list[dict]:
    """Crawl MemoryMarket: index + category pages + individual price pages."""
    all_entries: list[dict] = []
    visited: set[str] = set()

    async with httpx.AsyncClient(
        timeout=20,
        headers=BROWSER_HEADERS,
        follow_redirects=True,
    ) as client:
        # Step 1: fetch index page
        pages_to_visit = [INDEX_URL]
        category_entries: list[dict] = []

        while pages_to_visit:
            url = pages_to_visit.pop(0)
            if url in visited:
                continue
            visited.add(url)

            try:
                resp = await client.get(url)
                resp.raise_for_status()
                items = _parse_spot_tables(resp.text, url)
                category_entries.extend(items)
                logger.info(
                    "MemoryMarket: page %s — %d items (running total %d)",
                    url, len(items), len(category_entries),
                )
                # Discover new category/pagination links
                new_links = [
                    lnk for lnk in _collect_category_links(resp.text)
                    if lnk not in visited
                ]
                pages_to_visit.extend(new_links[:20])  # cap expansion
            except Exception:
                logger.warning(
                    "MemoryMarket: failed to fetch %s", url, exc_info=True,
                )

            await asyncio.sleep(PAGE_DELAY)

        # Step 2: probe individual price detail pages /price/in/1 .. /price/in/N
        detail_entries: list[dict] = []
        for pid in range(1, MAX_DETAIL_PAGES + 1):
            detail_url = f"{BASE_URL}/price/in/{pid}"
            if detail_url in visited:
                continue
            try:
                resp = await client.get(detail_url)
                if resp.status_code == 404:
                    # Assume sequential IDs; a 404 might just be a gap, continue
                    logger.debug("MemoryMarket: %s → 404, continuing", detail_url)
                    await asyncio.sleep(0.5)
                    continue
                resp.raise_for_status()
                items = _parse_spot_tables(resp.text, detail_url)
                detail_entries.extend(items)
                if items:
                    logger.info(
                        "MemoryMarket: detail page %d — %d items", pid, len(items),
                    )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    await asyncio.sleep(0.5)
                    continue
                logger.warning(
                    "MemoryMarket: detail page %d HTTP error %s",
                    pid, exc.response.status_code,
                )
            except Exception:
                logger.warning(
                    "MemoryMarket: detail page %d failed", pid, exc_info=True,
                )

            await asyncio.sleep(PAGE_DELAY)

        all_entries = category_entries + detail_entries

        # Attach rate-converted RUB prices
        for entry in all_entries:
            if entry["price_usd"] and rate_usd_rub:
                entry["price_rub"] = round(entry["price_usd"] * rate_usd_rub, 2)

    logger.info("MemoryMarket: crawl complete, %d total entries", len(all_entries))
    return all_entries
