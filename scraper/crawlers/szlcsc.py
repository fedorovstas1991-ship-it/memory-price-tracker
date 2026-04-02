"""SZLCSC full-catalog crawler.

Searches category keywords at so.szlcsc.com and paginates through all pages
by incrementing the pageIndex query parameter. Parses __NEXT_DATA__ JSON.
"""
import asyncio
import json
import logging

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

SEARCH_URL = "https://so.szlcsc.com/global.html"

# Approximate CNY→USD rate; no live rate available via CBR for CNY
CNY_TO_USD = 0.138

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

MAX_PAGES = 30
PAGE_SIZE = 30
PAGE_DELAY = 1.5


def _extract_products_from_next_data(html: str) -> tuple[list[dict], int]:
    """Parse __NEXT_DATA__ and return (products, total_count).

    total_count is the reported total number of results (-1 if unknown).
    """
    tree = HTMLParser(html)
    script = tree.css_first("script#__NEXT_DATA__")
    if not script:
        return [], -1

    try:
        data = json.loads(script.text())
    except (json.JSONDecodeError, TypeError):
        return [], -1

    props = data.get("props", {}).get("pageProps", {})

    # Primary path
    so_data = props.get("soData", {})
    search_result = so_data.get("searchResult", {})
    records = search_result.get("productRecordList", [])
    total = search_result.get("productCount", -1)

    if not records:
        # Fallback: generic scan for any list with productVO or productPriceList
        for val in props.values():
            if isinstance(val, dict):
                for v2 in val.values():
                    if isinstance(v2, list) and v2 and isinstance(v2[0], dict):
                        if "productVO" in v2[0] or "productPriceList" in v2[0]:
                            records = v2
                            break

    products = []
    for rec in records:
        if not isinstance(rec, dict):
            continue
        product = rec.get("productVO", rec)
        if not isinstance(product, dict):
            continue

        part_number = product.get("productModel") or product.get("productName") or ""
        description = product.get("productDescription") or product.get("describe") or ""
        stock = product.get("stockNumber") or product.get("stockCount") or 0
        price_list = product.get("productPriceList", [])

        best_cny = _best_price(price_list)
        if best_cny is None or best_cny <= 0:
            continue

        price_usd = round(best_cny * CNY_TO_USD, 2)

        products.append({
            "part_number": part_number,
            "description": description,
            "brand": extract_brand(part_number, description),
            "price_cny": round(best_cny, 2),
            "price_usd": price_usd,
            "stock": int(stock),
        })

    return products, int(total) if total != -1 else -1


def _best_price(price_list: list) -> float | None:
    best: float | None = None
    for tier in price_list:
        if not isinstance(tier, dict):
            continue
        qty = tier.get("startPurchasedNumber") or tier.get("ladder") or tier.get("startNumber") or 0
        price = tier.get("productPrice") or tier.get("price") or 0
        try:
            qty = int(qty)
            price = float(price)
        except (ValueError, TypeError):
            continue
        if qty <= 10:
            best = price
        elif best is None:
            best = price
    return best


async def crawl(rate_usd_rub: float) -> list[dict]:
    """Crawl SZLCSC for all CATEGORIES with pagination."""
    all_entries: list[dict] = []

    async with httpx.AsyncClient(
        timeout=20,
        headers=BROWSER_HEADERS,
        follow_redirects=True,
    ) as client:
        for category in CATEGORIES:
            category_count = 0

            for page in range(1, MAX_PAGES + 1):
                params = {"k": category, "pageIndex": page, "pageSize": PAGE_SIZE}
                try:
                    resp = await client.get(SEARCH_URL, params=params)
                    resp.raise_for_status()
                    products, total = _extract_products_from_next_data(resp.text)

                    if not products:
                        logger.info(
                            "SZLCSC: category=%r page %d — no items, stopping",
                            category, page,
                        )
                        break

                    for p in products:
                        price_rub = round(p["price_usd"] * rate_usd_rub, 2) if rate_usd_rub else None
                        all_entries.append({
                            "chip_type": category,
                            "part_number": p["part_number"],
                            "description": p["description"],
                            "brand": p["brand"],
                            "capacity": "",
                            "source": "szlcsc",
                            "distributor": "SZLCSC",
                            "price_usd": p["price_usd"],
                            "price_rub": price_rub,
                            "price_cny": p["price_cny"],
                            "moq": 1,
                            "stock": p["stock"],
                            "url": f"https://so.szlcsc.com/global.html?k={p['part_number']}",
                        })

                    category_count += len(products)
                    max_page = (total // PAGE_SIZE + 1) if total > 0 else MAX_PAGES
                    logger.info(
                        "SZLCSC: category=%r page %d/%d, %d items on page, %d total",
                        category, page, max_page, len(products), category_count,
                    )

                    if total > 0 and category_count >= total:
                        break
                    if len(products) < PAGE_SIZE:
                        break

                    await asyncio.sleep(PAGE_DELAY)

                except Exception:
                    logger.warning(
                        "SZLCSC: category=%r page %d — error, skipping",
                        category, page, exc_info=True,
                    )
                    break

            logger.info("SZLCSC: category=%r done, %d items", category, category_count)

    logger.info("SZLCSC: crawl complete, %d total entries", len(all_entries))
    return all_entries
