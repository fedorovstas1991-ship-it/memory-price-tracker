import json
import logging
from datetime import datetime, timezone

import httpx
from selectolax.parser import HTMLParser

from src.config import WATCHLIST, REQUEST_TIMEOUT
from src.models import PriceEntry
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

SZLCSC_SEARCH_URL = "https://so.szlcsc.com/global.html?k={part_number}"
CNY_TO_USD_APPROX = 0.14  # Approximate, will be overridden by actual rate

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _extract_product_vo_list(props: dict) -> list[dict]:
    """Extract a flat list of productVO dicts from pageProps using known paths."""
    # Path used by live site: soData.searchResult.productRecordList[*].productVO
    try:
        records = (
            props.get("soData", {})
            .get("searchResult", {})
            .get("productRecordList", [])
        )
        if records and isinstance(records[0], dict) and "productVO" in records[0]:
            return [r["productVO"] for r in records if isinstance(r.get("productVO"), dict)]
    except Exception:
        pass

    # Fallback path: direct productList (fixture / spec format)
    product_list = props.get("productList", [])
    if not product_list:
        product_list = props.get("data", {}).get("productList", [])

    # Generic scan: any top-level list/dict that looks like product records
    if not product_list:
        for val in props.values():
            if isinstance(val, list) and val and isinstance(val[0], dict):
                if "productPriceList" in val[0] or "productModel" in val[0]:
                    return val
            elif isinstance(val, dict):
                for v2 in val.values():
                    if isinstance(v2, list) and v2 and isinstance(v2[0], dict):
                        if any(k in v2[0] for k in ["productPriceList", "productModel", "productName"]):
                            return v2

    return product_list


def _best_price_from_tiers(price_list: list) -> float | None:
    """Return the lowest-MOQ price from a productPriceList tier array."""
    best: float | None = None
    for tier in price_list:
        if not isinstance(tier, dict):
            continue
        # Live site uses startPurchasedNumber; fixture/spec uses ladder or startNumber
        qty = tier.get("startPurchasedNumber", tier.get("ladder", tier.get("startNumber", 0)))
        price = tier.get("productPrice", tier.get("price", 0))
        try:
            price = float(price)
            qty = int(qty)
        except (ValueError, TypeError):
            continue
        if qty <= 10:
            best = price
        elif best is None:
            best = price
    return best


def parse_szlcsc_products(html: str) -> list[dict]:
    """Parse product data from SZLCSC __NEXT_DATA__ JSON."""
    tree = HTMLParser(html)
    script = tree.css_first("script#__NEXT_DATA__")
    if not script:
        return []

    try:
        data = json.loads(script.text())
    except (json.JSONDecodeError, TypeError):
        return []

    products = []
    try:
        props = data.get("props", {}).get("pageProps", {})
        product_vo_list = _extract_product_vo_list(props)
    except Exception:
        product_vo_list = []

    for product in product_vo_list:
        if not isinstance(product, dict):
            continue
        part_number = product.get("productModel", product.get("productName", ""))
        price_list = product.get("productPriceList", [])
        stock = product.get("stockNumber", product.get("stockCount", 0))

        best_price_cny = _best_price_from_tiers(price_list)

        if best_price_cny is None or best_price_cny <= 0:
            continue

        products.append({
            "part_number": part_number,
            "price_cny": round(best_price_cny, 2),
            "stock": int(stock) if stock else 0,
        })

    # If no products from __NEXT_DATA__, try JSON-LD (handles both Product and ItemList)
    if not products:
        for script_tag in tree.css("script[type='application/ld+json']"):
            try:
                ld = json.loads(script_tag.text())
                # Direct Product node
                if ld.get("@type") == "Product" and "offers" in ld:
                    price = float(ld["offers"].get("price", 0))
                    if price > 0:
                        products.append({
                            "part_number": ld.get("name", ""),
                            "price_cny": round(price, 2),
                            "stock": 0,
                        })
                # ItemList wrapping Product nodes (live site format)
                elif ld.get("@type") == "ItemList":
                    for item in ld.get("itemListElement", []):
                        product_node = item.get("item", {})
                        if product_node.get("@type") == "Product" and "offers" in product_node:
                            price = float(product_node["offers"].get("price", 0))
                            if price > 0:
                                products.append({
                                    "part_number": product_node.get("name", ""),
                                    "price_cny": round(price, 2),
                                    "stock": 0,
                                })
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

    return products


class SzlcscScraper(BaseScraper):
    name = "szlcsc"

    async def fetch_prices(self, rate_usd_rub: float) -> list[PriceEntry]:
        entries = []
        # CNY to USD approximate rate (CBR doesn't provide CNY directly)
        cny_to_usd = CNY_TO_USD_APPROX

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers=BROWSER_HEADERS, follow_redirects=True) as client:
            for part_number, chip_type, description, capacity in WATCHLIST:
                try:
                    url = SZLCSC_SEARCH_URL.format(part_number=part_number)
                    resp = await client.get(url)
                    resp.raise_for_status()
                    products = parse_szlcsc_products(resp.text)
                    now = datetime.now(timezone.utc)
                    for p in products:
                        price_usd = round(p["price_cny"] * cny_to_usd, 2)
                        price_rub = round(price_usd * rate_usd_rub, 2)
                        entries.append(PriceEntry(
                            chip_type=chip_type,
                            part_number=p["part_number"],
                            description=f"{description} (SZLCSC)",
                            capacity=capacity,
                            source="szlcsc",
                            price_usd=price_usd,
                            price_rub=price_rub,
                            moq=1,
                            url=url,
                            fetched_at=now,
                        ))
                except Exception:
                    logger.warning("SZLCSC: failed to fetch %s", part_number, exc_info=True)
        return entries
