import logging
from datetime import datetime, timezone

import httpx
from selectolax.parser import HTMLParser

from src.currency import convert_usd_to_rub
from src.models import PriceEntry
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

MEMORYMARKET_URL = "https://www.memorymarket.com/"


def parse_spot_table(html: str) -> list[dict]:
    tree = HTMLParser(html)
    rows = []
    for table in tree.css("table"):
        headers = [th.text(strip=True).lower() for th in table.css("thead th")]
        if not headers:
            continue
        for tr in table.css("tbody tr"):
            cells = [td.text(strip=True) for td in tr.css("td")]
            if len(cells) < 3:
                continue
            try:
                price_str = cells[2].replace(",", "").replace("$", "")
                price = float(price_str) if price_str else 0.0
            except ValueError:
                continue
            change_str = cells[3] if len(cells) > 3 else "0%"
            rows.append({
                "product": cells[0],
                "spec": cells[1] if len(cells) > 1 else "",
                "price_usd": price,
                "change": change_str,
            })
    return rows


class MemoryMarketScraper(BaseScraper):
    name = "memorymarket"

    async def fetch_prices(self, rate_usd_rub: float) -> list[PriceEntry]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(MEMORYMARKET_URL)
                resp.raise_for_status()
                html = resp.text
        except Exception:
            logger.warning("MemoryMarket: failed to fetch page", exc_info=True)
            return []

        rows = parse_spot_table(html)
        now = datetime.now(timezone.utc)
        entries = []
        for row in rows:
            product = row["product"]
            entries.append(PriceEntry(
                chip_type=product,
                part_number=f"{product} {row['spec']}",
                description=f"{product} {row['spec']} spot",
                capacity=row["spec"],
                source="memorymarket",
                price_usd=row["price_usd"],
                price_rub=convert_usd_to_rub(row["price_usd"], rate_usd_rub),
                moq=0,
                url=MEMORYMARKET_URL,
                fetched_at=now,
            ))
        return entries
