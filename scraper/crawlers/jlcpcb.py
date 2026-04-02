"""JLCPCB full-catalog crawler.

POSTs to the JLCPCB component search API with category keywords and
paginates through all pages (currentPage=1, 2, 3, ...).
"""
import asyncio
import logging

import httpx

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

JLCPCB_API_URL = (
    "https://jlcpcb.com/api/overseas-pcb-order/v1/shoppingCart/smtGood"
    "/selectSmtComponentList"
)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://jlcpcb.com",
    "Referer": "https://jlcpcb.com/parts/componentSearch",
}

PAGE_SIZE = 25
MAX_PAGES = 40
PAGE_DELAY = 1.5


def _best_price(price_tiers: list[dict], max_qty: int = 10) -> float | None:
    """Return the lowest unit price for any tier with startNumber <= max_qty."""
    best: float | None = None
    for tier in price_tiers:
        start = tier.get("startNumber", 0)
        price = tier.get("productPrice")
        if price is None:
            continue
        try:
            start = int(start)
            price = float(price)
        except (ValueError, TypeError):
            continue
        if start <= max_qty:
            if best is None or price < best:
                best = price
    return best


async def crawl(rate_usd_rub: float) -> list[dict]:
    """Crawl JLCPCB parts API for all CATEGORIES with pagination."""
    all_entries: list[dict] = []

    async with httpx.AsyncClient(
        timeout=20,
        headers=BROWSER_HEADERS,
    ) as client:
        for category in CATEGORIES:
            category_count = 0
            total_records = None  # will be set after first page

            for page in range(1, MAX_PAGES + 1):
                payload = {
                    "keyword": category,
                    "currentPage": page,
                    "pageSize": PAGE_SIZE,
                }
                try:
                    resp = await client.post(JLCPCB_API_URL, json=payload)
                    resp.raise_for_status()
                    data = resp.json()

                    page_info = (
                        data.get("data", {}).get("componentPageInfo", {})
                    )
                    items: list[dict] = page_info.get("list", [])

                    if total_records is None:
                        total_records = page_info.get("totalCount", 0)

                    if not items:
                        logger.info(
                            "JLCPCB: category=%r page %d — no items, stopping",
                            category, page,
                        )
                        break

                    for item in items:
                        part_number = item.get("componentModelEn") or item.get("componentModel") or ""
                        description = item.get("describe") or item.get("description") or ""
                        price_tiers = item.get("componentPrices", [])
                        price_usd = _best_price(price_tiers)
                        if price_usd is None or price_usd <= 0:
                            continue

                        moq = item.get("minPurchaseNum", 1)
                        stock = item.get("stockCount", 0)
                        url = item.get("lcscGoodsUrl") or ""
                        price_rub = round(price_usd * rate_usd_rub, 2) if rate_usd_rub else None

                        all_entries.append({
                            "chip_type": category,
                            "part_number": part_number,
                            "description": description,
                            "brand": extract_brand(part_number, description),
                            "capacity": "",
                            "source": "jlcpcb",
                            "distributor": "JLCPCB",
                            "price_usd": round(price_usd, 2),
                            "price_rub": price_rub,
                            "price_cny": None,
                            "moq": moq,
                            "stock": stock,
                            "url": url,
                        })

                    category_count += len(items)
                    max_pages_est = (total_records // PAGE_SIZE + 1) if total_records else MAX_PAGES
                    logger.info(
                        "JLCPCB: category=%r page %d/%d, %d items on page, %d total",
                        category, page, max_pages_est, len(items), category_count,
                    )

                    if total_records and category_count >= total_records:
                        break
                    if len(items) < PAGE_SIZE:
                        break

                    await asyncio.sleep(PAGE_DELAY)

                except Exception:
                    logger.warning(
                        "JLCPCB: category=%r page %d — error, skipping",
                        category, page, exc_info=True,
                    )
                    break

            logger.info("JLCPCB: category=%r done, %d items", category, category_count)

    logger.info("JLCPCB: crawl complete, %d total entries", len(all_entries))
    return all_entries
