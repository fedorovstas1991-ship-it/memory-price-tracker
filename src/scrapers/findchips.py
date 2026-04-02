import json
import logging
from datetime import datetime, timezone
from html import unescape

import httpx
from selectolax.parser import HTMLParser

from src.config import WATCHLIST, REQUEST_TIMEOUT
from src.currency import convert_usd_to_rub
from src.models import PriceEntry
from src.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

FINDCHIPS_URL = "https://www.findchips.com/search/{part_number}"
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def parse_findchips_results(html: str, part_number: str) -> list[dict]:
    """Parse distributor rows from FindChips HTML."""
    tree = HTMLParser(html)
    results = []
    seen = set()
    for tr in tree.css("tr[data-distributor_name][data-price]"):
        distributor = tr.attributes.get("data-distributor_name", "")
        mfr_part = tr.attributes.get("data-mfrpartnumber", "")
        stock_str = tr.attributes.get("data-instock", "0")
        price_raw = tr.attributes.get("data-price", "[]")

        if not distributor or not price_raw:
            continue

        # Deduplicate by distributor
        key = f"{distributor}:{mfr_part}"
        if key in seen:
            continue
        seen.add(key)

        try:
            price_data = json.loads(unescape(price_raw))
        except (json.JSONDecodeError, TypeError):
            continue

        # Find best USD price (pick the 10-unit tier or lowest qty available)
        best_price = None
        for tier in price_data:
            if len(tier) >= 3 and tier[1] == "USD":
                qty = int(tier[0])
                price = float(tier[2])
                if qty <= 10:
                    best_price = price
                elif best_price is None:
                    best_price = price

        if best_price is None or best_price <= 0:
            continue

        try:
            stock = int(stock_str.replace(",", ""))
        except ValueError:
            stock = 0

        results.append({
            "distributor": distributor,
            "part_number": mfr_part or part_number,
            "price_usd": round(best_price, 2),
            "stock": stock,
        })
    return results


class FindChipsScraper(BaseScraper):
    name = "findchips"

    async def fetch_prices(self, rate_usd_rub: float) -> list[PriceEntry]:
        entries = []
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, headers=BROWSER_HEADERS, follow_redirects=True) as client:
            for part_number, chip_type, description, capacity in WATCHLIST:
                try:
                    url = FINDCHIPS_URL.format(part_number=part_number)
                    resp = await client.get(url)
                    resp.raise_for_status()
                    results = parse_findchips_results(resp.text, part_number)
                    now = datetime.now(timezone.utc)
                    for r in results:
                        entries.append(PriceEntry(
                            chip_type=chip_type,
                            part_number=r["part_number"],
                            description=f"{description} via {r['distributor']}",
                            capacity=capacity,
                            source=f"findchips/{r['distributor']}",
                            price_usd=r["price_usd"],
                            price_rub=convert_usd_to_rub(r["price_usd"], rate_usd_rub),
                            moq=1,
                            url=FINDCHIPS_URL.format(part_number=part_number),
                            fetched_at=now,
                        ))
                except Exception:
                    logger.warning("FindChips: failed to fetch %s", part_number, exc_info=True)
        return entries
