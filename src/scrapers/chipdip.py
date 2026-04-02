import logging
import re
from datetime import datetime, timezone

import httpx
from selectolax.parser import HTMLParser

from src.currency import convert_rub_to_usd
from src.models import PriceEntry
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

CHIPDIP_CATALOG_URL = "https://www.chipdip.ru/catalog-show/ic-memory"


def parse_chipdip_catalog(html: str) -> list[dict]:
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
        items.append({
            "part_number": part_number,
            "description": desc_el.text(strip=True) if desc_el else "",
            "price_rub": price_rub,
            "url": url,
        })
    return items


def _parse_rub_price(text: str) -> float:
    cleaned = re.sub(r"[^\d,.]", "", text).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


class ChipDipScraper(BaseScraper):
    name = "chipdip"

    async def fetch_prices(self, rate_usd_rub: float) -> list[PriceEntry]:
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(
                    CHIPDIP_CATALOG_URL,
                    headers={"Accept-Language": "ru-RU,ru;q=0.9"},
                )
                resp.raise_for_status()
                html = resp.text
        except Exception:
            logger.warning("ChipDip: failed to fetch catalog", exc_info=True)
            return []

        items = parse_chipdip_catalog(html)
        now = datetime.now(timezone.utc)
        entries = []
        for item in items:
            entries.append(PriceEntry(
                chip_type="Memory IC",
                part_number=item["part_number"],
                description=item["description"],
                capacity="",
                source="chipdip",
                price_usd=convert_rub_to_usd(item["price_rub"], rate_usd_rub),
                price_rub=item["price_rub"],
                moq=1,
                url=item["url"],
                fetched_at=now,
            ))
        return entries
